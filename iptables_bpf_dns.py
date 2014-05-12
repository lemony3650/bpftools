#!/usr/bin/env python

template = r'''
#!/bin/bash
#
# This script is ***AUTOGENERATED***
#
# This is a script for applying and removing xt_bpf iptable rule. This
# particular rule was created with:
#
#     %(bpf_cmd)s
#
# To apply the iptables BPF rule against listed destination IP's run:
#
#    ./%(fname)s %(sampleips)s
#
# With the ip addresses of flooded name servers - destination IP of
# the packets.
#
# To clean the iptables rule:
#
#    ./%(fname)s --delete
#
#
# For the record, here's the BPF assembly:
#
%(assembly)s
#

set -o noclobber
set -o errexit
set -o nounset
set -o pipefail

: ${IPTABLES:="%(iptables)s"}
: ${IPSET:="ipset"}
: ${INPUTPLACE:="4"}
: ${DEFAULTINT:=`awk 'BEGIN {n=0} $2 == "00000000" {n=1; print $1; exit} END {if (n=0) {print "eth0"}}' /proc/net/route`}

iptablesrule () {
    ${IPTABLES} \
        ${*} \
        -i ${DEFAULTINT} \
        -p udp --dport 53 \
        -m set --match-set %(ipsetname)s dst \
        -m bpf --bytecode "%(bytecode)s" \
        -j DROP
}

if [ "$*" == "--delete" ]; then

    A=`(iptablesrule -C INPUT || echo "error") 2>/dev/null`
    if [ "${A}" != "error" ]; then
        iptablesrule -D INPUT
    fi
    ${IPSET} -exist destroy %(ipsetname)s 2>/dev/null

else

    ${IPSET} -exist create %(ipsetname)s hash:net family %(ipsetfamily)s
    while [ "$*" != "" ]; do
        ${IPSET} -exist add %(ipsetname)s "$1"
        shift
    done

    A=`(iptablesrule -C INPUT || echo "error") 2>/dev/null`
    if [ "${A}" == "error" ]; then
        iptablesrule -I INPUT ${INPUTPLACE}
    fi

fi
'''.lstrip()

import argparse
import os
import stat
import string
import sys

import gen_dns


parser = argparse.ArgumentParser(description=r'''

This program generates a bash script. The script when run will insert
(or remove) an iptable rule and ipset. The iptable rule drops traffic
that matches the BPF rule, which in turn is generated from given
parameters.



'''.strip())
parser.add_argument('-4', '--inet4', action='store_true',
                    help=argparse.SUPPRESS)
parser.add_argument('-6', '--inet6', action='store_true',
                    help='generate script for IPv6')
parser.add_argument('-w', '--write', metavar='file',
                    help='name the generated script')
parser.add_argument('type', nargs=1, choices=['dns'],
                    help='use BPF generator type (must be "dns")')
parser.add_argument('parameters', nargs='*',
                    help='parameters for the BPF generator')

args = parser.parse_args()
if not args or len(args.type) != 1:
    parser.print_help()
    sys.exit(-1)
args.type = args.type[0]

inet = 4 if not args.inet6 else 6

if args.type == 'dns':
    gen = gen_dns.generate(args.parameters,
                           inet=inet,
                           l3off=0)
else:
    assert False, args.type


if int(gen.bytecode.split(',')[0]) > 63:
    raise Exception("bytecode too long!")

name = 'bpf_%s_ip%s_%s' % (args.type, inet, gen.name)

fname = args.write or name + '.sh'

if fname == '-':
    f = sys.stdout
else:
    f = open(fname, 'wb')

ctx = {
    'bpf_cmd': gen.cmd,
    'bytecode': gen.bytecode,
    'assembly': '#    ' + '\n#    '.join(gen.assembly.split('\n')),
    'fname': fname if fname != '-' else name + '.sh',
    'ipsetname': name[:31],
}

if inet == 4:
    ctx.update({
            'iptables': 'iptables',
            'ipsetfamily': 'inet',
            'sampleips': '1.1.1.1/32',
            })
else:
    ctx.update({
            'iptables': 'ip6tables',
            'ipsetfamily': 'inet6',
            'sampleips': '2a00:1450:4009:803::1008/128',
            })

f.write(template % ctx)
f.flush()

if f != sys.stdout:
    print "Generated file %r" % (fname,)
    os.chmod(fname, 0750)

