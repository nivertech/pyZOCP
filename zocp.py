# Z25 Orchestror Control Protocol
# Copyright (c) 2013, Stichting z25.org, All rights reserved.
# Copyright (c) 2013, Arnaud Loonstra, All rights reserved.
# 
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 3.0 of the License, or (at your option) any later version.
# 
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public
# License along with this library.

import sys
sys.path.append('../')

from pyre import Pyre
import json
import zmq
import uuid

def dict_get(d, keys):
    """
    returns a value from a nested dict
    keys argument must be list

    raises a KeyError exception if failed
    """
    for key in keys:
        d = d[key]
    return d

def dict_set(d, keys, value):
    """
    sets a value in a nested dict
    keys argument must be a list
    returns the new updated dict

    raises a KeyError exception if failed
    """
    for key in keys[:-1]: 
        d = d[key]
    d[keys[-1]] = value

def dict_get_keys(d, keylist=""):
    for k, v in d.items():
        if isinstance(v, dict):
            # entering branch add seperator and enter
            keylist=keylist+".%s" %k
            keylist = dict_get_keys(v, keylist)
        else:
            # going back save this branch
            keylist = "%s.%s\n%s" %(keylist, k, keylist)
            #print(keylist)
    return keylist
              
# http://stackoverflow.com/questions/38987/how-can-i-merge-union-two-python-dictionaries-in-a-single-expression?rq=1
def dict_merge(a, b, path=None):
    """
    merges b into a, overwites a with b if equal
    """
    if not isinstance(a, dict):
        return b
    if path is None: path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                dict_merge(a[key], b[key], path + [str(key)])
            else:
                a[key] = b[key]
        else:
            a[key] = b[key]
    return a

class ZOCP(Pyre):

    def __init__(self, capability={}):
        super().__init__()
        self.peers = {} # id : capability data
        self.name = capability.get('_name')
        self.capability = capability
        self._running = False
        # We always join the ZOCP group
        self.join("ZOCP")
        #self.run()

    def get_peer_capability(self, peer):
        # construct a bson object with the request
        msg = json.dumps({'GET': 0})
        self.whisper(peer, msg.encode('utf-8'))

    # methods called on events. These can be overwritten
    def on_peer_enter(self, peer, *args, **kwargs):
        print("ZOCP ENTER  : %s" %(peer.hex))

    def on_peer_exit(self, peer, *args, **kwargs):
        print("ZOCP EXIT   : %s" %(peer.hex))

    def on_peer_join(self, peer, grp, *args, **kwargs):
        print("ZOCP JOIN   : %s joined group %s" %(peer.hex, grp))

    def on_peer_leave(self, peer, grp, *args, **kwargs):
        print("ZOCP LEAVE  : %s left group %s" %(peer.hex, grp))

    def on_peer_whisper(self, peer, *args, **kwargs):
        print("ZOCP WHISPER: %s whispered: %s" %(peer.hex, args))

    def on_peer_shout(self, peer, grp, *args, **kwargs):
        print("ZOCP SHOUT  : %s shouted in group %s: %s" %(peer.hex, grp, args))

    def on_modified(self):
        if self._running:
            self.shout("ZOCP", json.dumps({ 'PUT' :self.capability}).encode('utf-8'))

    def get_message(self):
        # A message coming from a zre node contains:
        # * msg type
        # * msg peer id
        # * group (if group type)
        # * the actual message
        msg = self.get_socket().recv_multipart()
        type = msg.pop(0).decode('utf-8')
        peer = uuid.UUID(bytes=msg.pop(0))
        grp=None
        if type == "ENTER":
            if not peer in self.peers.keys():
                self.peers.update({peer: ""})
            self.get_peer_capability(peer)
            self.on_peer_enter(peer, msg)
            return
        if type == "EXIT":
            self.peers.pop(peer)
            self.on_peer_exit(peer, msg)
            return
        if type == "JOIN":
            grp = msg.pop(0)
            self.on_peer_join(peer, grp, msg)
            return
        elif type == "LEAVE":
            grp = msg.pop(0)
            self.on_peer_leave(peer, grp, msg)
            return
        if type == "SHOUT":
            grp = msg.pop(0)
            self.on_peer_shout(peer, grp, msg)
        elif type == "WHISPER":
            self.on_peer_whisper(peer, msg)
        else:
            return

        try:
            msg = json.loads(msg.pop(0).decode('utf-8'))
        except Exception as e:
            print("ERROR: %s" %e)
        else:
            for method in msg.keys():
                if method == 'GET':
                    self.handle_GET(msg[method], peer, grp)
                elif method == 'POST':
                    self.handle_POST(msg[method], peer, grp)
                elif method == 'PUT':
                    self.handle_PUT(msg[method], peer, grp)
                else:
                    try:
                        func = getattr(obj, 'handle_'+method)
                        func(msg[method])
                    except:
                        raise Exception('No %s method on resource: %s' %(method,object))

    def handle_GET(self, data, peer, grp=None):
        #print("GET: %s, %s, %s" % (data, peer, grp))
        if not data:
            data = {'PUT': self.get_capability()}
            self.whisper(peer, json.dumps(data).encode('utf-8'))
            return
        else:
            # first is the object to retrieve from
            # second is the items list of items to retrieve
            ret = {}
            for get_item in data:
                ret[get_item] = self.capability.get(get_item)
            self.whisper(peer, json.dumps({ 'PUT' :ret}).encode('utf-8'))

    def handle_POST(self, data, peer, grp):
        #print("POST: %s, %s, %s" % (data, peer, grp))
        self.capability = dict_merge(self.capability, data)
        self.on_modified()

    def handle_PUT(self, data, peer, grp):
        #print("PUT: %s, %s, %s" % (data, peer, grp))
        self.peers[peer] = dict_merge(self.peers.get(peer), data)

    # set nodes capability, overwites previous
    def set_capability(self, cap):
        self.capability = cap
        self.on_modified()

    # return the capabilties
    def get_capability(self):
        return self.capability

    def set_node_name(self, name):
        self.capability['_name'] = name
        self.on_modified()

    def get_node_name(self, name):
        return self.capability.get('_name')

    def register_int(self, name, int, access='r', min=None, max=None, step=None):
        self.capability[name] = {'value': int, 'typeHint': 'int', 'access':access }
        if min:
            self.capability[name]['min'] = min
        if max:
            self.capability[name]['max'] = max
        if step:
            self.capability[name]['step'] = step
        self.on_modified()

    def register_float(self, name, flt, access='r', min=None, max=None, step=None):
        print(type(flt))
        self.capability[name] = {'value': flt, 'typeHint': 'float', 'access':access }
        if min:
            self.capability[name]['min'] = min
        if max:
            self.capability[name]['max'] = max
        if step:
            self.capability[name]['step'] = step
        self.on_modified()

    def register_percent(self, name, pct, access='r', min=None, max=None, step=None):
        self.capability[name] = {'value': pct, 'typeHint': 'percent', 'access':access }
        if min:
            self.capability[name]['min'] = min
        if max:
            self.capability[name]['max'] = max
        if step:
            self.capability[name]['step'] = step
        self.on_modified()

    def register_bool(self, name, bl, access='r'):
        self.capability[name] = {'value': bl, 'typeHint': 'bool', 'access':access }
        self.on_modified()

    def run(self):
        poller = zmq.Poller()
        poller.register(self.get_socket(), zmq.POLLIN)
        self._running = True
        while(self._running):
            try:
                items = dict(poller.poll())
                if self.get_socket() in items and items[self.get_socket()] == zmq.POLLIN:
                    self.get_message()
            except (KeyboardInterrupt, SystemExit):
                break
        self.stop()

if __name__ == '__main__':
    
#     dataDict = {
#     "a":{
#         "r": 1,
#         "s": 2,
#         "t": 3
#         },
#     "b":{
#         "u": 1,
#         "v": {
#             "x": 1,
#             "y": 2,
#             "z": 3
#         },
#         "w": 3
#         }
#     }
#     print(" should print 2")
#     print(dict_get(dataDict, ["a", "s"]))
#     dict_set(dataDict, ["a", "s"], 3)
#     print(" should print 3")
#     print(dict_get(dataDict, ["a", "s"]))
#     a = []
#     print(dict_get_keys(dataDict))
#     sys.exit()

    z = ZOCP()
    z.set_node_name("ZOCP-Test")
    z.register_bool("zocpBool", True, 'rw')
    z.register_float("zocpFloat", 2.3, 'rw', 0, 5.0, 0.1)
    z.register_int('zocpInt', 10, access='rw', min=-10, max=10, step=1)
    z.register_percent('zocpPercent', 12, access='rw')
    z.run()
    z.stop()
    print("FINISH")