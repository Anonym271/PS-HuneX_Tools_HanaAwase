#!/usr/bin/env python
#
# allpac.hed/.nam/.mrg extraction & creation utility
# For more information, see EXTR hed.md, REIN hed.md and specs/hed_format.md
"""hedutil version 1.0, Copyright (C) 2014 Nanashi3.

hedutil comes with ABSOLUTELY NO WARRANTY.

Script to unpack or repack a .hed/.nam/.mrg triple
"""

import os, errno
import sys
import argparse
from sys import stderr
from struct import unpack, unpack_from, pack
import yaml
from collections import OrderedDict
from base64 import b64encode

class CustomException(Exception):
    pass


class CustHelpAction(argparse._HelpAction):
    def __call__(self, parser, namespace, values, option_string=None):
        parser.print_help()
        for subparser_action in parser._actions:
            if isinstance(subparser_action, argparse._SubParsersAction):
                for choice, subparser in subparser_action.choices.items():
                    print("\n\n== {} ==".format(choice))
                    print(subparser.format_help())
        parser.exit()


def ordereddict_constructor(loader, node):
    try:
        omap = loader.construct_yaml_omap(node)
        return OrderedDict(*omap)
    except yaml.constructor.ConstructorError:
        return loader.construct_yaml_seq(node)

#def represent_ordereddict(dumper, data):
#    value = []
#
#    for item_key, item_value in data.items():
#        node_key = dumper.represent_data(item_key)
#        node_value = dumper.represent_data(item_value)
#
#        value.append((node_key, node_value))
#
#    return yaml.nodes.MappingNode(u'tag:yaml.org,2002:map', value)

def represent_ordereddict(dumper, data):
    # TODO: Again, adjust for preferred flow style, and other stylistic details
    # NOTE: For block style this uses the compact omap notation, but for flow style
    # it does not.
    values = []
    node = yaml.SequenceNode(u'tag:yaml.org,2002:seq', values, flow_style=True)
    if dumper.alias_key is not None:
        dumper.represented_objects[dumper.alias_key] = node
    for key, value in data.items():
        key_item = dumper.represent_data(key)
        value_item = dumper.represent_data(value)
        node_item = yaml.MappingNode(u'tag:yaml.org,2002:map', [(key_item, value_item)],
                                     flow_style=False)
        values.append(node_item)
    return node


LINE_WIDTH = 88

def write_line(strline):
    print(strline * LINE_WIDTH, file=stderr)


class HedEntry:
    """Describes one file in the mrg archive"""

    def __init__(self, block, name=''):
        self.name = name
        if len(block) == 8:
            ofs_low, ofs_high, size_sect, size_low = unpack('<HHHH', block)
            self.offset = 0x800 * (ofs_low | ((ofs_high & 0xF000) << 4))
            self.rounded_size = self.size = 0x800 * size_sect
            if size_low == 0:
                self.size = self.rounded_size
            else:
                self.size = size_low | 0x800 * ((size_sect - 1) & 0xFFFF0000)

        elif len(block) == 4:
            ofs_low, ofssz_high = unpack('<HH', block)
            self.offset = 0x800 * (ofs_low | ((ofssz_high & 0xF000) << 4))
            self.rounded_size = self.size = 0x800 * (ofssz_high & 0x0FFF)
        
        else:
            raise ValueError('HedEntry constructor expects either a 4-byte or 8-byte binary block, source file may be incomplete')
            

    def to_block(self, blocksize):
        if blocksize == 8:
            ofs_aligned = self.offset // 0x800
            ofs_low = ofs_aligned & 0xFFFF
            ofs_high = (ofs_aligned & 0xF0000) >> 4
            size_low = self.size & 0xFFFF
            if size_low == 0:
                size_sect = self.size // 0x800
            else:
                size_sect = self.size // 0x800 + 1
            return pack('<HHHH', ofs_low, ofs_high, size_sect, size_low)
            
        elif blocksize == 4:
            ofssz_high = self.size // 0x800
            ofs_aligned = self.offset // 0x800
            ofs_low = ofs_aligned & 0xFFFF
            ofssz_high = (ofs_aligned & 0xF0000) >> 4
            return pack('<HH', ofs_low, ofssz_high)

def makedir(dirname):
    try:
        os.makedirs(dirname)
    except OSError as exc: # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(dirname):
            pass
        else: raise

def writefile_in_directory_with_collisions(dirpath, ent, mrgfile, collision_suffix):
    if (ent.name is None) or (len(ent.name) == 0):
        newname = collision_suffix
        path = os.path.join(dirpath, newname)
    else:
        newname = None
        path = os.path.join(dirpath, ent.name)

        if os.path.isfile(path):
            root, ext = os.path.splitext(ent.name)
            newname = root + '-' + collision_suffix + ext
            path = os.path.join(dirpath, newname)

    mrgfile.seek(ent.offset)    
    with open(path, 'wb') as f:
        f.write(mrgfile.read(ent.size))

    return newname  # None or string

def read_0_string(bstr):
    try:
        return bstr[0:bstr.index(b'\x00')].decode('ASCII')
    except ValueError:
        return bstr.decode('ASCII')

def get_entry_index_by_name(entries_list, name):
    for idx in range(len(entries_list)):
        if entries_list[idx]['name'] == name:
            return idx
    return -1


def write_entry_with_padding(infile, entry, outfile):
    outfile.seek(entry.offset)
    remaining = entry.size
    while remaining > 32768:
        outfile.write(infile.read(32768))
        remaining -= 32768
    if remaining > 0:
        outfile.write(infile.read(remaining))
    complement = entry.size & 0x7FF
    if complement > 0:
        while complement & 0xF != 0:
            outfile.write(b'\x00')
            complement += 1
        while complement & 0x7FF != 0:
            outfile.write(b'\x0C' + 15 * b'\x00')
            complement += 0x10


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    subparsers = parser.add_subparsers(title='subcommands', dest='subcommand')

    parser_unpack = subparsers.add_parser('unpack', help='unpack hed/nam/mrg and optionally create a filelist')
    parser_unpack.add_argument('-f', '--filelist', 
            default=None, dest='filelist',
            help='Output filelist path (default: none -- only unpack files)')
    parser_unpack.add_argument('input', metavar='input.hed', help='Input .hed file')

    parser_replace = subparsers.add_parser('replace', help='replace an archive entry in-place and modify an existing filelist')
    parser_replace.add_argument('-f', '--filelist', 
            required=True, dest='filelist', type=argparse.FileType('r'),
            help='Subject filelist path, modified in-place [REQUIRED]')
    parser_replace.add_argument('-s', '--source-file', 
            required=True, dest='source', metavar='sourcepath', type=argparse.FileType('rb'),
            help='File path to inserted file [REQUIRED]')
    replace_group = parser_replace.add_mutually_exclusive_group()
    replace_group.add_argument('-i', '--index', 
            default=None, dest='index', type=int,
            help='Refer to replaced entry by index')
    replace_group.add_argument('-n', '--name', 
            default=None, dest='name',
            help='Refer to replaced entry by name')    
    parser_replace.add_argument('subject', metavar='existing.hed', help='Subject .hed file, modified in-place. Same basename is used for .nam/.mrg')

    parser_repack = subparsers.add_parser('repack', help='generate a hed/nam/mrg triple from an existing filelist')
    parser_repack.add_argument('-f', '--filelist', 
            required=True, dest='filelist', type=argparse.FileType('r'),
            help='Input filelist path [REQUIRED]')
    parser_repack.add_argument('output', metavar='output.hed', help='Output .hed file. Same basename is used for .nam/.mrg')

    parser.add_argument('-h', '--help',
            action=CustHelpAction, default=argparse.SUPPRESS,
            help='show this help message and exit')

    return parser, parser.parse_args()


def unpack_verb(args):
    basestem = os.path.splitext(os.path.basename(args.input))[0]
    in_hed = args.input
    in_nam = basestem + '.nam'
    in_mrg = basestem + '.mrg'
    hedfile = namfile = mrgfile = None
    outputdir = basestem + '-unpacked'

    try:
        if str.upper(os.path.splitext(args.input)[1]) != '.HED':
            raise CustomException("'{}' must be a .hed file".format(args.input))
        hedfile = open(in_hed, 'rb')
        if os.path.isfile(in_nam): namfile = open(in_nam, 'rb')
        mrgfile = open(in_mrg, 'rb')
        makedir(outputdir)
    except Exception as exc:
        print("ERR: [{1}] failed to process \"{0}\" - {2}".format(args.input, type(exc).__name__, str(exc)), file=stderr)
        sys.exit(1)

    foo, first_entry_high = unpack('<HH', hedfile.read(0x04))
    entry_length = 8 if (first_entry_high & 0x0FFF) == 0 else 4
    record_count = os.path.getsize(in_hed) // entry_length
    write_line('-')
    print("| Archive count: {0} entries".format(record_count), file=stderr)
    write_line('-')
    hedfile.seek(0)
    indexed_fmt = '{0:04d}' if record_count < 10000 else '{0:06d}'

    yamlobj = OrderedDict()
    yamlobj['original name'] = args.input
    yamlobj['storage directory'] = outputdir
    yamlobj['hed record length'] = entry_length
    yamlobj['has nam filelist'] = namfile is not None
    yamlobj['entries'] = []
    for i in range(record_count):
        blob = hedfile.read(entry_length)
        first_word, = unpack_from('<L', blob)
        if first_word == 0xFFFFFFFF:
            continue
        namfilename = None if namfile is None else read_0_string(namfile.read(0x20))
        entry = HedEntry(blob, name=namfilename)
        print("|- {0} - {1} b".format(entry.name, entry.size), file=stderr)
        newfilename = writefile_in_directory_with_collisions(outputdir, entry, mrgfile, collision_suffix=indexed_fmt.format(i))
        yamlobj['entries'].append({'name': namfilename, 'path': newfilename if newfilename is not None else entry.name})

    write_line('=')
    if args.filelist is not None:
        with open(args.filelist, 'wt', newline='') as yamlfile:
            yaml.dump(yamlobj, yamlfile)
        print('Filelist: {}'.format(args.filelist), file=stderr)
    print('Output Directory: {}'.format(outputdir), file=stderr)


def replace_verb(args):
    if (args.index is None) and (args.name is None):
        print("ERR: failed to process \"{0}\" - you need to specify either --index or --name for replacing an entry".format(args.filelist.name), file=stderr)
        sys.exit(1)

    basestem = os.path.splitext(os.path.basename(args.subject))[0]
    in_hed = args.subject
    in_mrg = basestem + '.mrg'
    hedfile = mrgfile = None
    srcfile = None

    try:
        if str.upper(os.path.splitext(args.subject)[1]) != '.HED':
            raise CustomException("'{}' must be a .hed file".format(args.input))
        hedfile = open(in_hed, 'r+b')
        mrgfile = open(in_mrg, 'r+b')
    except Exception as exc:
        print("ERR: [{1}] failed to process \"{0}\" - {2}".format(args.subject, type(exc).__name__, str(exc)), file=stderr)
        sys.exit(1)


    search_by_name = args.name is not None
    yamlobj = None
    try:
        yamlobj = yaml.load(args.filelist)
    except yaml.YAMLError as exc:
        print("ERR: [{1}] failed to process \"{0}\" - {2}".format(args.filelist.name, type(exc).__name__, str(exc)), file=stderr)
        sys.exit(1)

    print('Loaded Filelist: {0} >> {1}'.format(yamlobj['original name'], yamlobj['storage directory']), file=stderr)
    entry_length = yamlobj['hed record length']

    if not search_by_name:
        if (args.index < 0) or (args.index >= len(yamlobj['entries'])):
            print("ERR: failed to process \"{0}\" - replace by --index '{1}' out of bounds [0, {2}]".format(args.filelist.name, args.index, len(yamlobj['entries']) - 1), file=stderr)
            sys.exit(1)
    else:
        if yamlobj['has nam filelist'] == False:
            print("ERR: failed to process \"{0}\" - replace by --name '{1}' while no .nam is used for this .hed. Use --index instead".format(args.filelist.name, args.name), file=stderr)
            sys.exit(1)
            
        args.index = get_entry_index_by_name(yamlobj['entries'], args.name)
        if (args.index < 0):
            print("ERR: failed to process \"{0}\" - replace by --name '{1}' entry not found. Check if file case matches".format(args.filelist.name, args.name), file=stderr)
            sys.exit(1)

    hedfile.seek(args.index * entry_length)
    entry = HedEntry(hedfile.read(entry_length))
    print('Replacing: idx={0} {1} - orgOfs-Sz:{2:08X}-{3}b'.format(args.index, yamlobj['entries'][args.index]['path'], entry.offset, entry.size), file=stderr)
    
    if os.path.getsize(args.source.name) > entry.rounded_size:
        mrgfile.seek(0, 2)
        entry.offset = mrgfile.tell()  # should be on 0x800 boundary
    entry.size = os.path.getsize(args.source.name)
    size_low = entry.size & 0xFFFF
    size_sect = entry.size // 0x800
    entry.rounded_size = 0x800 * size_sect if size_low == 0 else 0x800 * (size_sect + 1)
    write_entry_with_padding(args.source, entry, mrgfile)
    
    hedfile.seek(args.index * entry_length)
    hedfile.write(entry.to_block(entry_length))

    yamlobj['entries'][args.index]['path'] = args.source.name

    try:
        # reopen with truncation
        with open(args.filelist.name, 'wt', newline='') as yamlfile:
            yaml.dump(yamlobj, yamlfile)
        print('Filelist: {}'.format(args.filelist.name), file=stderr)
    except Exception as exc:
        print("ERR: [{1}] failed to write filelist into \"{0}\" - {2}".format(args.filelist.name, type(exc).__name__, str(exc)), file=stderr)
        try:
            failsafe = 'failsafe.yml' 
            print(">> Attempting to save filelist as \"{}\" in current directory".format(failsafe), file=stderr)
            with open(failsafe, 'wt', newline='') as yamlfile:
                yaml.dump(yamlobj, yamlfile)
        except Exception as exc:
            print("ERR: could not save to \"{}\" either. Dumping as base64 in console...".format(failsafe), file=stderr)
            print(b64encode(yaml.dump(yamlobj).encode('utf-8')))
        print(">> Failsafe save OK, please manually rename it as {}.".format(args.filelist.name), file=stderr)
        sys.exit(2)


def repack_verb(args):
    # TODO
    raise CustomException("Sorry, this option is not implemented yet")

############
# __main__ #
############

if __name__ == '__main__':

    yaml.add_constructor(u'tag:yaml.org,2002:seq', ordereddict_constructor)
    yaml.add_representer(OrderedDict, represent_ordereddict)

    parser, args = parse_args()
    if (args.subcommand == "unpack"): unpack_verb(args)
    elif (args.subcommand == "replace"): replace_verb(args)
    elif (args.subcommand == "repack"): repack_verb(args)
    else:
        parser.print_usage()
        sys.exit(20)
    sys.exit(0)

