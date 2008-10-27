#####################################################################
# Copyright (c) 2008-2009 Kalamazoo Community Mental Health Services,
#   John Holland <jholland@kazoocmh.org> <john@zoner.org>
# All rights reserved.
#
# This software is licensed as described in the file LICENSE.txt, which
# you should have received as part of this distribution.
#
######################################################################

#
#    $Id$

"""
Parse a ANSI X12 data file.

Maintain context state
Start saving context and segments
Interface to read and alter segments

TODO: 
    Return loop start and end for segment outside of context tree 
    Attach errors to returned dicts
"""

import os, os.path

# Intrapackage imports
import pyx12
#import error_handler
import errors
import map_index
import map_if
import x12file
from map_walker import walk_tree, pop_to_parent_loop, get_pop_loops, \
    get_push_loops

class X12DataNode(object):
    """
    Capture the segment data and X12 definition for a loop subtree
    Alter relational data
    Iterate over contents
    """
    def __init__(self, x12_node, seg_data, ntype='seg'):
        """
        """
        self.x12_map_node = x12_node
        self.type = ntype
        self.seg_data = seg_data
        self.parent = None
        self.children = []
        self.errors = []

    # Properties
    def _get_id(self):
        """
        @return: x12 node id
        @rtype: string
        """
        return self.x12_map_node.id

    id = property(_get_id, None, None)

    def _get_cur_path(self):
        """
        @return: x12 node path
        @rtype: string
        """
        return self.x12_map_node.get_path()

    cur_path = property(_get_cur_path, None, None)

    # Public Methods
    #def addSegment(self, x12_node, seg_data):
    #    new_data_node = X12DataNode(x12_node, seg_data, 'seg')
    #    match_path = x12_node.get_path()

    def iterate_segments(self):
        """
        Iterate over this node and children, return any segments found 
        """
        raise errors.EngineError, 'old'
        if self.type == 'seg':
            yield {'type': 'seg', 'id': self.x12_map_node.id, \
                'segment': self.seg_data}
        for child in self.children:
            print self.type
            for a in child.iterate_segments():
                yield a

    def iterate_loop_segments(self):
        """
        Iterate over this node and children, return loop start and loop end 
        and any segments found 
        """
        raise errors.EngineError, 'old'
        if self.type == 'loop':
            yield {'type': 'loop_start', 'id': self.id, \
                'node': self.x12_map_node}
        elif self.type == 'seg':
            yield {'type': 'seg', 'id': self.id, \
                'segment': self.seg_data}
        for child in self.children:
            for a in child.iterate_loop_segments():
                yield a
        if self.type == 'loop':
            yield {'type': 'loop_end', 'id': self.id, \
                'node': self.x12_map_node}

    # Private Methods
    def _is_child_path(self, root_path, child_path):
        """
        Is the child path really a child of the root path?
        @type root_path: string
        @type child_path: string
        @return: True if a child
        @rtype: boolean
        """
        root = root_path.split('/')
        child = child_path.split('/')
        if len(root) >= len(child):
            return False
        for i in range(len(root)):
            if root[i] != child[i]:
                return False
        return True

    #def _addLoop(self, x12_node):
    #    new_loop = X12DataNode(x12_node, None, 'loop')

class X12LoopDataNode(X12DataNode):
    """
    Capture the X12 definition for a loop subtree
    Alter relational data
    Iterate over contents
    """
    def __init__(self, x12_node):
        self.x12_map_node = x12_node
        self.type = 'loop'
        self.seg_data = None
        self.parent = None
        self.children = []
        self.errors = []

    def iterate_segments(self):
        """
        Iterate over this node and children
        """
        for child in self.children:
            for a in child.iterate_segments():
                yield a

    def iterate_loop_segments(self):
        """
        Iterate over this node and children, return loop start and loop end 
        """
        yield {'type': 'loop_start', 'id': self.id, 'node': self.x12_map_node}
        for child in self.children:
            for a in child.iterate_loop_segments():
                yield a
        yield {'type': 'loop_end', 'id': self.id, 'node': self.x12_map_node}


class X12SegmentDataNode(X12DataNode):
    """
    Capture the segment data and X12 definition
    Alter relational data
    Iterate over contents
    """
    def __init__(self, x12_node, seg_data, parent=None, start_loops=[], \
            end_loops=[]):
        self.x12_map_node = x12_node
        self.type = 'seg'
        self.seg_data = seg_data
        self.parent = parent
        self.start_loops = start_loops
        self.end_loops = end_loops
        self.errors = []

    def iterate_segments(self):
        """
        Iterate on this node, return the segment
        """
        yield {'type': 'seg', 'id': self.x12_map_node.id, \
            'segment': self.seg_data}

    def iterate_loop_segments(self):
        """
        Iterate over this node and children, return loop start and loop end 
        and any segments found 
        """
        for loop in self.start_loops:
            yield {'node': loop, 'type': 'loop_start', 'id': loop.id}
        yield {'type': 'seg', 'id': self.id, 'segment': self.seg_data, \
            'start_loops': self.start_loops, 'end_loops': self.end_loops}
        for loop in self.end_loops:
            yield {'node': loop, 'type': 'loop_end', 'id': loop.id}


class X12ContextReader(object):
    """
    Read an X12 input stream
    Keep context when needed

    """

    def __init__(self, param, errh, src_file_obj, xslt_files = []):
        """
        @param param: pyx12.param instance
        @param errh: Error Handler object
        @param src_file_obj: Source document
        @type src_file_obj: string
        @rtype: boolean
        """
        map_path = param.get('map_path')
        self.param = param
        self.errh = errh
        self.xslt_files = xslt_files
        self.icvn = None
        self.fic = None
        self.vriic = None
        self.tspc = None
        
        # Get X12 DATA file
        self.src = x12file.X12Reader(src_file_obj) 

        #Get Map of Control Segments
        self.map_file = 'x12.control.00401.xml'
        self.control_map = map_if.load_map_file(os.path.join(map_path, \
            self.map_file), param)
        self.map_index_if = map_index.map_index(os.path.join(map_path, \
            'maps.xml'))
        self.x12_map_node = self.control_map.getnodebypath('/ISA_LOOP/ISA')
        self.walker = walk_tree()

    def iter_segments(self, loop_id=None):
        """
        Simple segment or tree iterator
        @return: X12 Data Node - simple segment or tree
        @rtype: L{node<x12context.X12DataNode>}
        """
        #map_abbr = 'x12'
        cur_tree = None
        cur_data_node = None
        for seg in self.src:
            #find node
            orig_node = self.x12_map_node
            
            if seg.get_seg_id() == 'ISA':
                tpath = '/ISA_LOOP/ISA'
                self.x12_map_node = self.control_map.getnodebypath(tpath)
            elif seg.get_seg_id() == 'GS':
                tpath = '/ISA_LOOP/GS_LOOP/GS'
                self.x12_map_node = self.control_map.getnodebypath(tpath)
            else:
                try:
                    self.x12_map_node = self.walker.walk(self.x12_map_node, \
                        seg, self.errh, self.src.get_seg_count(), \
                        self.src.get_cur_line(), self.src.get_ls_id())
                except errors.EngineError:
                    raise
            if self.x12_map_node is None:
                self.x12_map_node = orig_node
            else:
                if seg.get_seg_id() == 'ISA':
                    self. errh.add_isa_loop(seg, self.src)
                    icvn = seg.get_value('ISA12')
                    self.errh.handle_errors(self.src.pop_errors())
                elif seg.get_seg_id() == 'IEA':
                    self.errh.handle_errors(self.src.pop_errors())
                    self.errh.close_isa_loop(self.x12_map_node, seg, self.src)
                elif seg.get_seg_id() == 'GS':
                    fic = seg.get_value('GS01')
                    vriic = seg.get_value('GS08')
                    map_file_new = self.map_index_if.get_filename(icvn, \
                        vriic, fic)
                    if self.map_file != map_file_new:
                        #map_abbr = self.map_index_if.get_abbr(icvn, vriic, fic)
                        self.map_file = map_file_new
                        if self.map_file is None:
                            raise pyx12.errors.EngineError, \
                                "Map not found.  icvn=%s, fic=%s, vriic=%s" % \
                                (icvn, fic, vriic)
                        cur_map = map_if.load_map_file(self.map_file, \
                            self.param, self.xslt_files)
                        self._apply_loop_count(orig_node, cur_map)
                        self._reset_isa_counts(cur_map)
                    self._reset_gs_counts(cur_map)
                    tpath = '/ISA_LOOP/GS_LOOP/GS'
                    self.x12_map_node = cur_map.getnodebypath(tpath)
                    self.errh.add_gs_loop(seg, self.src)
                    self.errh.handle_errors(self.src.pop_errors())
                elif seg.get_seg_id() == 'BHT':
                    if vriic in ('004010X094', '004010X094A1'):
                        tspc = seg.get_value('BHT02')
                        map_file_new = self.map_index_if.get_filename(icvn, \
                            vriic, fic, tspc)
                        if self.map_file != map_file_new:
                            #map_abbr = self.map_index_if.get_abbr(icvn, \
                            #    vriic, fic, tspc)
                            self.map_file = map_file_new
                            if self.map_file is None:
                                err_str = "Map not found.  icvn=%s, fic=%s, vriic=%s, tspc=%s" % \
                                    (icvn, fic, vriic, tspc)
                                raise pyx12.errors.EngineError, err_str
                            cur_map = map_if.load_map_file(self.map_file, \
                                self.param, self.xslt_files)
                            self._apply_loop_count(self.x12_map_node, cur_map)
                            tpath = '/ISA_LOOP/GS_LOOP/ST_LOOP/HEADER/BHT'
                            self.x12_map_node = cur_map.getnodebypath(tpath)
                    self.errh.add_seg(self.x12_map_node, seg, \
                        self.src.get_seg_count(), \
                        self.src.get_cur_line(), self.src.get_ls_id())
                    self.errh.handle_errors(self.src.pop_errors())
                elif seg.get_seg_id() == 'GE':
                    self.errh.handle_errors(self.src.pop_errors())
                    self.errh.close_gs_loop(self.x12_map_node, seg, self.src)
                elif seg.get_seg_id() == 'ST':
                    self.errh.add_st_loop(seg, self.src)
                    self.errh.handle_errors(self.src.pop_errors())
                elif seg.get_seg_id() == 'SE':
                    self.errh.handle_errors(self.src.pop_errors())
                    self.errh.close_st_loop(self.x12_map_node, seg, self.src)
                else:
                    self.errh.add_seg(self.x12_map_node, seg, \
                        self.src.get_seg_count(), \
                        self.src.get_cur_line(), self.src.get_ls_id())
                    self.errh.handle_errors(self.src.pop_errors())

            node_path = self._get_path_list(self.x12_map_node.get_path())
            # If we are in the requested tree, wait until we have the whole thing
            if loop_id is not None and loop_id in node_path:
                # Are we at the start of the requested tree? 
                if node_path[-2] == loop_id and \
                        self.x12_map_node.is_first_seg_in_loop():
                    # Found loop repeat. Close existing, create new tree
                    if cur_tree is not None:
                        yield cur_tree
                    # Make new tree on parent loop
                    cur_tree = X12LoopDataNode(self.x12_map_node.parent)
                    cur_data_node = cur_tree
                    cur_data_node = self._add_segment(cur_data_node, \
                        self.x12_map_node, seg)
                else:
                    cur_data_node = self._add_segment(cur_data_node, \
                        self.x12_map_node, seg)
            else:
                if cur_tree is not None:
                    # We have completed a tree
                    yield cur_tree
                    cur_tree = None
                if cur_data_node is not None:
                    push_loops = get_push_loops(cur_data_node.x12_map_node, \
                            self.x12_map_node)
                    pop_loops = get_pop_loops(cur_data_node.x12_map_node, \
                            self.x12_map_node)
                    cur_data_node = X12SegmentDataNode(self.x12_map_node, seg, \
                            None, push_loops, pop_loops)
                else:
                    cur_data_node = X12SegmentDataNode(self.x12_map_node, seg)
                yield cur_data_node
        
    def register_error_callback(self, callback, err_type):
        """
        Future:  Callbacks for X12 validation errors
        """
        pass

    def _add_segment(self, cur_data_node, segment_x12_node, seg_data):
        """
        From the last position in the X12 Data Node Tree, find the correct
        position for the new segment.  Move up or down the tree as appropriate.
        Do not need to deal with loop repeats

        @param cur_data_node: Current X12 Data Node
        @type cur_data_node: L{node<x12context.X12DataNode>}
        @param segment_x12_node: Segment Map Node
        @type segment_x12_node: L{node<map_if.x12_node>}
        @return: New X12 Data Node
        @rtype: L{node<x12context.X12DataNode>}
        """
        # Logic copied from x12xml
        if not segment_x12_node.is_segment():
            raise errors.EngineError, 'Node must be a segment'
        # Get enclosing loop
        parent_x12_node = pop_to_parent_loop(segment_x12_node) 
        # check path for new loops to be added
        new_path_list = self._get_path_list(parent_x12_node.get_path())
        last_path_list = self._get_path_list(cur_data_node.cur_path)
        if last_path_list != new_path_list:
            #match_idx = self._get_path_match_idx(last_path_list, new_path_list, segment_x12_node)
            for x12_loop in get_pop_loops(cur_data_node.x12_map_node, segment_x12_node):
                cur_data_node = cur_data_node.parent
                if cur_data_node.id != x12_loop.id:
                    raise errors.EngineError, 'Loop pop: %s != %s' % (cur_data_node.id, x12_loop.id)
            #for i in range(match_idx, len(new_path_list)):
            for x12_loop in get_push_loops(cur_data_node.x12_map_node, \
                    segment_x12_node):
                # push new loop nodes, if needed
                cur_data_node = self._add_loop_node(x12_loop, cur_data_node)
        new_node = X12SegmentDataNode(self.x12_map_node, seg_data)
        cur_data_node.children.append(new_node)
        new_node.parent = cur_data_node
        cur_data_node = new_node
        return cur_data_node

    def _add_loop_node(self, x12_loop_node, cur_data_node): #, seg_x12_node):
        """
        Add a loop data node the the current tree location
        @param x12_loop_node: X12 Loop node
        @type x12_loop_node: L{node<map_if.loop_if>}
        @param cur_data_node: Current X12 Data Node
        @type cur_data_node: L{node<x12context.X12DataNode>}
        @param seg_x12_node: Segment Map Node
        @type seg_x12_node: L{node<map_if.x12_node>}
        @return: New X12 Data Node
        @rtype: L{node<x12context.X12DataNode>}
        """
        #parent_loop = self._get_parent_x12_loop(loop_id, seg_x12_node)
        new_node = X12LoopDataNode(x12_loop_node)
        cur_data_node.children.append(new_node)
        new_node.parent = cur_data_node
        return new_node

    def _apply_loop_count(self, orig_node, new_map):
        """
        Apply loop counts to current map
        """
        ct_list = []
        orig_node.get_counts_list(ct_list)
        for (path, ct) in ct_list:
            curnode = new_map.getnodebypath(path)
            curnode.set_cur_count(ct)

    def _get_path_list(self, path_str):
        """
        Get list of path nodes from path string
        @rtype: list
        """
        return filter(lambda x: x!='', path_str.split('/'))

#    def _get_path_match_idx(self, last_path, cur_path, seg_x12_node):
#        """
#        Get the index of the last matching path nodes
#        @param last_path: list of map ids
#        @type last_path: list of strings 
#        @param cur_path: list of map ids
#        @type cur_path: list of strings 
#        @param seg_x12_node: Segment Map Node
#        @type seg_x12_node: L{node<map_if.x12_node>}
#        """
#        match_idx = 0
#        for i in range(min(len(cur_path), len(last_path))):
#            if cur_path[i] != last_path[i]:
#                break
#            match_idx += 1
#        root_path = self._get_root_path(last_path, cur_path)
#        if seg_x12_node.is_first_seg_in_loop() \
#                and root_path == cur_path:
#            match_idx -= 1
#        return match_idx

#    def _get_parent_x12_loop(self, loop_id, start_x12_node):
#        """
#        From a segment X12 node, return the matching parent x12 loop node
#        """
#        x12_node = start_x12_node
#        while not x12_node.is_map_root():
#            if x12_node.id == loop_id:
#                return x12_node
#            else:
#                x12_node = x12_node.parent
#        return None

#    def _get_root_path(self, path_list1, path_list2):
#        """
#        @param path_list1: list of map ids
#        @type path_list1: list of strings 
#        @param path_list2: list of map ids
#        @type path_list2: list of strings 
#        @return: Common path prefix
#        @rtype: list of strings 
#        """
#        return self._get_path_list(os.path.commonprefix(
#            ['/'.join(path_list1), '/'.join(path_list2)]))

    #def _get_loop_pop_list(self, old_path_list, new_path_list):

    def _reset_isa_counts(self, cur_map):
        """
        Reset ISA instance counts
        """
        cur_map.getnodebypath('/ISA_LOOP').set_cur_count(1)
        cur_map.getnodebypath('/ISA_LOOP/ISA').set_cur_count(1)

    def _reset_gs_counts(self, cur_map):
        """
        Reset GS instance counts
        """
        cur_map.getnodebypath('/ISA_LOOP/GS_LOOP').reset_cur_count()
        cur_map.getnodebypath('/ISA_LOOP/GS_LOOP').set_cur_count(1)
        cur_map.getnodebypath('/ISA_LOOP/GS_LOOP/GS').set_cur_count(1)
