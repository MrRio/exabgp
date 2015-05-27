# encoding: utf-8
"""
text.py

Created by Thomas Mangin on 2009-08-25.
Copyright (c) 2009-2015 Exa Networks. All rights reserved.
"""

# ***********************************
# *******************************
# ***************************
# NOT IN use
# ***************************
# *******************************
# ***********************************

from exabgp.configuration.current import Configuration
from exabgp.configuration.format import formated

from exabgp.protocol.family import AFI
from exabgp.protocol.family import SAFI
from exabgp.protocol.family import Family
from exabgp.protocol.ip import IP
from exabgp.bgp.message import OUT

from exabgp.bgp.message.update.nlri.inet import INET
from exabgp.bgp.message.update.nlri.mpls import MPLS
from exabgp.bgp.message.refresh import RouteRefresh
from exabgp.bgp.message.operational import Advisory
from exabgp.bgp.message.operational import Query
from exabgp.bgp.message.operational import Response

from exabgp.rib.change import Change


# ========================================================================= Text
#

class Text (Configuration):
	def __init__ (self):
		Configuration.__init__(self,'','')
		# part of parent API, done here to remove pylint warning attribute-defined-outside-init
		self._nexthopself = None

	@staticmethod
	def extract_neighbors (command):
		"""return a list of neighbor definition : the neighbor definition is a list of string which are in the neighbor indexing string"""
		# This function returns a list and a string
		# The first list contains parsed neighbor to match against our defined peers
		# The string is the command to be run for those peers
		# The parsed neighbor is a list of the element making the neighbor string so each part can be checked against the neighbor name

		returned = []
		neighbor,remaining = command.split(' ',1)
		if neighbor != 'neighbor':
			return [],command

		ip,command = remaining.split(' ',1)
		definition = ['neighbor %s' % (ip)]

		while True:
			try:
				key,value,remaining = command.split(' ',2)
			except ValueError:
				key,value = command.split(' ',1)
			if key == ',':
				returned.append(definition)
				_,command = command.split(' ',1)
				definition = []
				continue
			if key not in ['neighbor','local-ip','local-as','peer-as','router-id','family-allowed']:
				if definition:
					returned.append(definition)
				break
			definition.append('%s %s' % (key,value))
			command = remaining

		return returned,command

	def api_route (self, command, peers, action):
		tokens = formated(command).split(' ')[1:]
		number = len(tokens)

		if number < 1:
			return False

		message = tokens[0]

		if message not in ('route',):
			return False

		if number == 2 and action == 'withdraw' and 'next-hop' not in tokens:
			tokens.extend(['next-hop','0.0.0.0'])

		changes = []
		if 'self' in command:
			for peer,nexthop in peers.iteritems():
				scope = [{}]
				self._nexthopself = nexthop
				if not self._single_static_route(scope,tokens[1:]):
					self._nexthopself = None
					return False
				for change in scope[0]['announce']:
					changes.append((peer,change))
			self._nexthopself = None
		else:
			scope = [{}]
			if not self._single_static_route(scope,tokens[1:]):
				return False
			for peer in peers:
				for change in scope[0]['announce']:
					changes.append((peer,change))

		if action == 'withdraw':
			for (peer,change) in changes:
				change.nlri.action = OUT.WITHDRAW
		return changes
	def api_vpls (self, command, peers, action):
		tokens = formated(command).split(' ')[1:]
		if len(tokens) < 4:
			return False
		if tokens[0] != 'vpls':
			return False
		changes = []
		if 'self' in command:
			for peer,nexthop in peers.iteritems():
				scope = [{}]
				self._nexthopself = nexthop
				if not self._single_l2vpn_vpls(scope,tokens[1:]):
					self._nexthopself = None
					return False
				for change in scope[0]['announce']:
					changes.append((peer,change))
			self._nexthopself = None
		else:
			scope = [{}]
			if not self._single_l2vpn_vpls(scope,tokens[1:]):
				return False
			for peer in peers:
				for change in scope[0]['announce']:
					changes.append((peer,change))
		if action == 'withdraw':
			for (peer,change) in changes:
				change.nlri.action = OUT.WITHDRAW
		return changes

	def api_attribute (self, command, peers, action):
		# This is a quick solution which does not support next-hop self
		attribute,nlris = command.split('nlri')
		route = '%s route 0.0.0.0/0 %s' % (action, ' '.join(attribute.split()[2:]))
		parsed = self.api_route(route,peers,action)
		if parsed in (True,False,None):
			return parsed
		attributes = parsed[0][1].attributes
		nexthop = parsed[0][1].nlri.nexthop
		changes = []
		for nlri in nlris.split():
			ip,mask = nlri.split('/')
			klass = MPLS if 'path-information' in command else INET
			change = Change(
				klass(
					afi=IP.toafi(ip),
					safi=IP.tosafi(ip),
					packed=IP.pton(ip),
					mask=int(mask),
					nexthop=nexthop.packed,
					action=action
				),
				attributes
			)
			if action == 'withdraw':
				change.nlri.action = OUT.WITHDRAW
			else:
				change.nlri.action = OUT.ANNOUNCE
			changes.append((peers.keys(),change))
		return changes

	def api_flow (self, command, action):
		command = command.replace('{','{\\n').replace('}','}\\n').replace(';',';\\n').replace('\\n\\n','\\n')
		self._tokens = self._tokenise(' '.join(formated(command).split(' ')[2:]).split('\\n'))
		scope = [{}]
		if not self._dispatch(scope,'flow',['route',],[],['root']):
			return False
		if not self._check_flow_route(scope):
			return False
		changes = scope[0]['announce']
		if action == 'withdraw':
			for change in changes:
				change.nlri.action = OUT.WITHDRAW
		return changes

	def api_refresh (self, command):
		tokens = formated(command).split(' ')[2:]
		if len(tokens) != 2:
			return False
		afi = AFI.value(tokens.pop(0))
		safi = SAFI.value(tokens.pop(0))
		if afi is None or safi is None:
			return False
		return RouteRefresh(afi,safi)

	def api_eor (self, command):
		tokens = formated(command).split(' ')[2:]
		number = len(tokens)

		if not number:
			return Family(1,1)

		if number != 2:
			return False

		afi = AFI.fromString(tokens[0])
		if afi == AFI.undefined:
			return False

		safi = SAFI.fromString(tokens[1])
		if safi == SAFI.undefined:
			return False

		return Family(afi,safi)

	def api_operational (self, command):
		tokens = formated(command).split(' ',2)
		scope = [{}]

		if len(tokens) != 3:
			return False

		operational = tokens[0].lower()
		what = tokens[1].lower()

		if operational != 'operational':
			return False

		if what == 'asm':
			if not self._single_operational(Advisory.ASM,scope,['afi','safi','advisory'],tokens[2]):
				return False
		elif what == 'adm':
			if not self._single_operational(Advisory.ADM,scope,['afi','safi','advisory'],tokens[2]):
				return False
		elif what == 'rpcq':
			if not self._single_operational(Query.RPCQ,scope,['afi','safi','sequence'],tokens[2]):
				return False
		elif what == 'rpcp':
			if not self._single_operational(Response.RPCP,scope,['afi','safi','sequence','counter'],tokens[2]):
				return False
		elif what == 'apcq':
			if not self._single_operational(Query.APCQ,scope,['afi','safi','sequence'],tokens[2]):
				return False
		elif what == 'apcp':
			if not self._single_operational(Response.APCP,scope,['afi','safi','sequence','counter'],tokens[2]):
				return False
		elif what == 'lpcq':
			if not self._single_operational(Query.LPCQ,scope,['afi','safi','sequence'],tokens[2]):
				return False
		elif what == 'lpcp':
			if not self._single_operational(Response.LPCP,scope,['afi','safi','sequence','counter'],tokens[2]):
				return False
		else:
			return False

		operational = scope[0]['operational'][0]
		return operational
