#!/usr/bin/env python
# encoding: utf-8
"""
glacier.py

MIT License

Copyright (C) 2012 and beyond by Urban Skudnik (urban.skudnik@gmail.com).

All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE."""

import sys
import os
import select
import ConfigParser
import argparse
import re
import json
import datetime
import dateutil.parser
import pytz
import locale
import time
from prettytable import PrettyTable

import boto
import glaciercorecalls

MAX_VAULT_NAME_LENGTH = 255
VAULT_NAME_ALLOWED_CHARACTERS = "[a-zA-Z\.\-\_0-9]+"
READ_PART_SIZE = glaciercorecalls.GlacierWriter.DEFAULT_PART_SIZE
locale.setlocale(locale.LC_ALL, '') # Empty string = use default setting

def progress(msg):
    if sys.stdout.isatty():
        print msg,
        sys.stdout.flush()

def check_vault_name(name):
    m = re.match(VAULT_NAME_ALLOWED_CHARACTERS, name)
    if len(name) > 255:
        raise Exception(u"Vault name can be at most 255 charecters long.")
    if len(name) == 0:
        raise Exception(u"Vault name has to be at least 1 character long.")
    if m.end() != len(name):
        raise Exception(u"Allowed characters are a–z, A–Z, 0–9, '_' (underscore),\
                          '-' (hyphen), and '.' (period)")
    return True

MAX_DESCRIPTION_LENGTH = 1024

def check_description(description):
    if len(description) > 1024:
        raise Exception(u"Description must be less or equal to 1024 characters.")

    for char in description:
        n = ord(char)
        if n < 32 or n > 126:
            raise Exception(u"The allowable characters are 7-bit ASCII without \
                              control codes, specifically ASCII values 32—126 \
                              decimal or 0x20—0x7E hexadecimal.")
    return True

def is_power_of_2(v):
    return (v & (v - 1)) == 0

def next_power_of_2(v):
    """
    Returns the next power of 2, or the argument if it's already a power of 2.
    """
    v -= 1
    v |= v >> 1
    v |= v >> 2
    v |= v >> 4
    v |= v >> 8
    v |= v >> 16
    return v + 1

def print_headers(response):
    table = PrettyTable(["Header", "Value"])
    for header in response.getheaders():
        if len(str(header[1])) < 100:
            table.add_row(header)
    print table

def parse_response(response):
    if response.status == 403:
        print "403 Forbidden."
        print "\n"
        print "Reason:"
        print response.read()
        print response.msg
    print response.status, response.reason
    if response.status == 204:
        print_headers(response)

def lsvault(args):
    region = args.region
    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)

    response = glacierconn.list_vaults()
    table = None
    while True:
        parse_response(response)
        jdata = json.loads(response.read())
        if response.status == 200 and len(jdata['VaultList']) > 0:
            if not table:
                headers = sorted(jdata['VaultList'][0].keys())
                table = PrettyTable(headers)
            for entry in jdata['VaultList']:
                table.add_row([locale.format('%d', entry[k], grouping=True) if k == 'SizeInBytes'
                              else entry[k] for k in headers])
            if jdata['Marker']:
                response = glacierconn.list_vaults(jdata['Marker'])
            else:
                break
        else:
            break

    if table:
        table.sortby = "VaultName"
        print table

def mkvault(args):
    vault_name = args.vault
    region = args.region

    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)

    if check_vault_name(vault_name):
        response = glaciercorecalls.GlacierVault(glacierconn, vault_name).create_vault()
        parse_response(response)
        print response.getheader("Location")

def rmvault(args):
    vault_name = args.vault
    region = args.region

    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)

    if check_vault_name(vault_name):
        response = glaciercorecalls.GlacierVault(glacierconn, vault_name).delete_vault()
        parse_response(response)

def describevault(args):
    vault_name = args.vault
    region = args.region

    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)

    if check_vault_name(vault_name):
        response = glaciercorecalls.GlacierVault(glacierconn, vault_name).describe_vault()
        parse_response(response)
        jdata = json.loads(response.read())
        table = PrettyTable(["LastInventory", "Archives", "Size", "ARN", "Created"])
        table.add_row([jdata['LastInventoryDate'], jdata['NumberOfArchives'],
                       locale.format('%d', jdata['SizeInBytes'], grouping=True),
                       jdata['VaultARN'], jdata['CreationDate']])
        print table

def listmultiparts(args):
    vault_name = args.vault
    region = args.region

    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)

    if check_vault_name(vault_name):
        response = glaciercorecalls.GlacierVault(glacierconn, vault_name).list_multipart_uploads()
        table = None
        while True:
            parse_response(response)
            jdata = json.loads(response.read())
            print "Marker: ", jdata['Marker']
            if response.status == 200 and len(jdata['UploadsList']) > 0:
                if not table:
                    headers = sorted(jdata['UploadsList'][0].keys())
                    table = PrettyTable(headers)
                for entry in jdata['UploadsList']:
                    table.add_row([locale.format('%d', entry[k], grouping=True) if k == 'PartSizeInBytes'
                                   else entry[k] for k in headers ])
                if jdata['Marker']:
                    response = glaciercorecalls.GlacierVault(glacierconn, vault_name).list_multipart_uploads(jdata['Marker'])
                else:
                    break
            else:
                break

        if table:
            print table

def abortmultipart(args):
    vault_name = args.vault
    region = args.region

    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)

    if check_vault_name(vault_name):
        response = glaciercorecalls.GlacierVault(glacierconn, vault_name).abort_multipart(args.uploadId)
        parse_response(response)

def listjobs(args):
    vault_name = args.vault
    region = args.region

    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)

    gv = glaciercorecalls.GlacierVault(glacierconn, name=vault_name)
    response = gv.list_jobs()
    parse_response(response)
    table = PrettyTable(["Action", "Archive ID", "Status", "Initiated",
                         "VaultARN", "Job ID"])
    for job in gv.job_list:
        table.add_row([job['Action'],
                       job['ArchiveId'],
                       job['StatusCode'],
                       job['CreationDate'],
                       job['VaultARN'],
                       job['JobId']])
    print table

def describejob(args):
    vault = args.vault
    jobid = args.jobid
    region = args.region
    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)

    gv = glaciercorecalls.GlacierVault(glacierconn, vault)
    gj = glaciercorecalls.GlacierJob(gv, job_id=jobid)
    gj.job_status()
    print "Archive ID: %s\nJob ID: %s\nCreated: %s\nStatus: %s\n" % (gj.archive_id,
                                                                     jobid, gj.created,
                                                                     gj.status_code)

# Formats file sizes in human readable format. Anything bigger than TB
# is returned is TB. Number of decimals is optional, defaults to 1.
def size_fmt(num, decimals = 1):
    fmt = "%%3.%sf %%s"% decimals
    for x in ['bytes','KB','MB','GB']:
        if num < 1024.0:
            return fmt % (num, x)
        num /= 1024.0
    return fmt % (num, 'TB')

def putarchive(args):
    region = args.region
    vault = args.vault
    filename = args.filename
    description = args.description
    stdin = args.stdin
    BOOKKEEPING= args.bookkeeping
    BOOKKEEPING_DOMAIN_NAME= args.bookkeeping_domain_name

    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)

    if BOOKKEEPING:
        sdb_conn = boto.connect_sdb(aws_access_key_id=args.aws_access_key,
                                    aws_secret_access_key=args.aws_secret_key)
        domain_name = BOOKKEEPING_DOMAIN_NAME
        try:
            domain = sdb_conn.get_domain(domain_name, validate=True)
        except boto.exception.SDBResponseError:
            domain = sdb_conn.create_domain(domain_name)

    if description:
        description = " ".join(description)
    else:
        description = filename

    if check_description(description):
        reader = None

        # if filename is given, use filename then look at stdio if theres something there
        if not stdin:
            try:
                reader = open(filename, 'rb')
                total_size = os.path.getsize(filename)
            except IOError:
                print "Couldn't access the file given."
                return False
        elif select.select([sys.stdin,],[],[],0.0)[0]:
            reader = sys.stdin
            total_size = 0
        else:
            print "Nothing to upload."
            return False

        if args.partsize < 0:
            # User did not specify part_size. Compute the optimal value.
            if total_size > 0:
                part_size = max(1, next_power_of_2(total_size / (1024*1024*10000)))
            else:
                part_size = glaciercorecalls.GlacierWriter.DEFAULT_PART_SIZE / 1024 / 1024
        else:
            part_size = next_power_of_2(args.partsize)

        if total_size > part_size * 1024 * 1024 * 10000:
            # User specified a value that is too small. Adjust.
            part_size = next_power_of_2(total_size / (1024*1024*10000))

        writer = glaciercorecalls.GlacierWriter(glacierconn, vault, description=description,
                                                part_size=(part_size*1024*1024))

        #Read file in chunks so we don't fill whole memory
        start_time = current_time = previous_time = time.time()
        for part in iter((lambda:reader.read(READ_PART_SIZE)), ''):

            writer.write(part)

            if total_size > 0:
                # Calculate transfer rates in bytes per second.
                current_time = time.time()
                current_rate = int(READ_PART_SIZE/(current_time - previous_time))
                overall_rate = int(writer.uploaded_size/(current_time - start_time))

                # Estimate finish time, based on overall transfer rate.
                if overall_rate > 0:
                    time_left = (total_size - writer.uploaded_size)/overall_rate
                    eta = time.strftime("%H:%M:%S", time.localtime(current_time + time_left))
                else:
                    time_left = "Unknown"
                    eta = "Unknown"

                progress('\rWrote %s of %s (%s%%). Rate %s/s, average %s/s, eta %s.' %
                         (size_fmt(writer.uploaded_size),
                          size_fmt(total_size),
                          int(100 * writer.uploaded_size/total_size),
                          size_fmt(current_rate, 2),
                          size_fmt(overall_rate, 2),
                          eta))

            else:
                progress('\rWrote %s bytes.' %
                    (locale.format('%d', writer.uploaded_size, grouping=True)))

            previous_time = current_time

        writer.close()
        current_time = time.time()
        if total_size > 0:
            progress('\rWrote %s of %s bytes (%s%%). Transfer rate %s.\n' %
                     (locale.format('%d', writer.uploaded_size, grouping=True),
                      locale.format('%d', total_size, grouping=True),
                      int(100 * writer.uploaded_size/total_size),
                      locale.format('%d', overall_rate, grouping=True)))
        else:
            progress('\rWrote %s bytes.\n' %
                (locale.format('%d', writer.uploaded_size, grouping=True)))


        archive_id = writer.get_archive_id()
        location = writer.get_location()
        sha256hash = writer.get_hash()
        if BOOKKEEPING:
            file_attrs = {
                'region':region,
                'vault':vault,
                'filename':filename,
                'archive_id': archive_id,
                'location':location,
                'description':description,
                'date':'%s' % datetime.datetime.utcnow().replace(tzinfo=pytz.utc),
                'hash':sha256hash
            }

            if args.name:
                file_attrs['filename'] = args.name
            elif stdin:
                file_attrs['filename'] = description

            domain.put_attributes(file_attrs['filename'], file_attrs)

        print "Created archive with ID: ", archive_id
        print "Archive SHA256 tree hash: ", sha256hash

def getarchive(args):
    region = args.region
    vault = args.vault
    archive = args.archive
    filename = args.filename

    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)
    gv = glaciercorecalls.GlacierVault(glacierconn, vault)

    jobs = gv.list_jobs()
    found = False
    for job in gv.job_list:
        if job['ArchiveId'] == archive:
            found = True
            # no need to start another archive retrieval
            if filename or not job['Completed']:
                print "ArchiveId: ", archive
            if job['Completed']:
                job2 = glaciercorecalls.GlacierJob(gv, job_id=job['JobId'])
                if filename:
                    ffile = open(filename, "w")
                    for part in iter((lambda:job2.get_output().read(READ_PART_SIZE)), ''):
                        ffile.write(part)
                    ffile.close()
                else:
                    print job2.get_output().read()
                return
    if not found:
        job = gv.retrieve_archive(archive)
        print "Started"

def download(args):
    region = args.region
    vault = args.vault
    filename = args.filename
    out_file = args.out_file

    if not filename:
        raise Exception(u"You have to pass in the file name or the search term \
                          of it's description to search through archive.")

    args.search_term = filename
    items = search(args, print_results=False)

    n_items = 0
    if not items:
        print "Sorry, didn't find anything."
        return False

    print "Region\tVault\tFilename\tArchive ID"
    for item in items:
        n_items += 1
        archive = item['archive_id']
        vault = item['vault']
        print "%s\t%s\t%s\t%s" % (item['region'],
                                  item['vault'],
                                  item['filename'],
                                  item['archive_id'])

    if n_items > 1:
        print "You need to uniquely identify file with either region, vault or \
               filename parameters. If that is not enough, use getarchive to \
               specify exactly which archive you want."
        return False

    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)
    gv = glaciercorecalls.GlacierVault(glacierconn, vault)

    jobs = gv.list_jobs()
    found = False
    for job in gv.job_list:
        if job['ArchiveId'] == archive:
            found = True
            # no need to start another archive retrieval
            if not job['Completed']:
                print "Waiting for Amazon Glacier to assamble the archive."
            if job['Completed']:
                job2 = glaciercorecalls.GlacierJob(gv, job_id=job['JobId'])
                if out_file:
                    ffile = open(out_file, "w")
                    ffile.write(job2.get_output().read())
                    ffile.close()
                else:
                    print job2.get_output().read()
            return True
    if not found:
        job = gv.retrieve_archive(archive)
        print "Started"

def deletearchive(args):
    region = args.region
    vault = args.vault
    archive = args.archive
    BOOKKEEPING= args.bookkeeping
    BOOKKEEPING_DOMAIN_NAME= args.bookkeeping_domain_name

    if BOOKKEEPING:
        sdb_conn = boto.connect_sdb(aws_access_key_id=args.aws_access_key,
                                    aws_secret_access_key=args.aws_secret_key)
        domain_name = BOOKKEEPING_DOMAIN_NAME
        try:
            domain = sdb_conn.get_domain(domain_name, validate=True)
        except boto.exception.SDBResponseError:
            domain = sdb_conn.create_domain(domain_name)

    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)
    gv = glaciercorecalls.GlacierVault(glacierconn, vault)

    parse_response( gv.delete_archive(archive) )

    # TODO: can't find a method for counting right now
    query = 'select * from `%s` where archive_id="%s"' % (BOOKKEEPING_DOMAIN_NAME, archive)
    items = domain.select(query)
    for item in items:
        domain.delete_item(item)

def search(args, print_results=True):
    region = args.region
    vault = args.vault
    search_term = args.search_term
    BOOKKEEPING= args.bookkeeping
    BOOKKEEPING_DOMAIN_NAME= args.bookkeeping_domain_name

    if BOOKKEEPING:
        sdb_conn = boto.connect_sdb(aws_access_key_id=args.aws_access_key,
                                    aws_secret_access_key=args.aws_secret_key)
        domain_name = BOOKKEEPING_DOMAIN_NAME
        try:
            domain = sdb_conn.get_domain(domain_name, validate=True)
        except boto.exception.SDBResponseError:
            domain = sdb_conn.create_domain(domain_name)
    else:
        raise Exception(u"You have to enable bookkeeping in your settings \
                          before you can perform search.")

    search_params = []
    table_title = ""
    if region:
        search_params += ["region='%s'" % (region,)]
    else:
        table_title += "Region\t"

    if vault:
        search_params += ["vault='%s'" % (vault,)]
    else:
        table_title += "Vault\t"

    table_title += "Filename\tArchive ID"

    if search_term:
        search_params += ["(filename like '"+ search_term+"%' or description like '"+search_term+"%')" ]
    search_params = " and ".join(search_params)

    query = 'select * from `%s` where %s' % (BOOKKEEPING_DOMAIN_NAME, search_params)
    items = domain.select(query)

    if print_results:
        print table_title

    for item in items:
        # print item, item.keys()
        item_attrs = []
        if not region:
            item_attrs += [item[u'region']]
        if not vault:
            item_attrs += [item[u'vault']]
        item_attrs += [item[u'filename']]
        item_attrs += [item[u'archive_id']]
        if print_results:
            print "\t".join(item_attrs)

    if not print_results:
        return items

def render_inventory(inventory):
    print "Inventory of vault: %s" % (inventory["VaultARN"],)
    print "Inventory Date: %s\n" % (inventory['InventoryDate'],)
    print "Content:"
    table = PrettyTable(["Archive Description", "Uploaded", "Size", "Archive ID", "SHA256 hash"])
    for archive in inventory['ArchiveList']:
        table.add_row([archive['ArchiveDescription'],
                       archive['CreationDate'],
                       locale.format('%d', archive['Size'], grouping=True),
                       archive['ArchiveId'],
                       archive['SHA256TreeHash']])
    print table

def inventory(args):
    region = args.region
    vault = args.vault
    force = args.force
    BOOKKEEPING= args.bookkeeping
    BOOKKEEPING_DOMAIN_NAME= args.bookkeeping_domain_name

    glacierconn = glaciercorecalls.GlacierConnection(args.aws_access_key, args.aws_secret_key, region=region)
    gv = glaciercorecalls.GlacierVault(glacierconn, vault)
    if force:
        job = gv.retrieve_inventory(format="JSON")
        return True
    try:
        gv.list_jobs()
        inventory_retrievals_done = []
        for job in gv.job_list:
            if job['Action'] == "InventoryRetrieval" and job['StatusCode'] == "Succeeded":
                d = dateutil.parser.parse(job['CompletionDate']).replace(tzinfo=pytz.utc)
                job['inventory_date'] = d
                inventory_retrievals_done += [job]

        if len(inventory_retrievals_done):
            list.sort(inventory_retrievals_done,
                      key=lambda i: i['inventory_date'], reverse=True)
            job = inventory_retrievals_done[0]
            print "Inventory with JobId:", job['JobId']
            job = glaciercorecalls.GlacierJob(gv, job_id=job['JobId'])
            inventory = json.loads(job.get_output().read())

            if BOOKKEEPING:
                sdb_conn = boto.connect_sdb(aws_access_key_id=args.aws_access_key,
                                            aws_secret_access_key=args.aws_secret_key)
                domain_name = BOOKKEEPING_DOMAIN_NAME
                try:
                    domain = sdb_conn.get_domain(domain_name, validate=True)
                except boto.exception.SDBResponseError:
                    domain = sdb_conn.create_domain(domain_name)

                d = dateutil.parser.parse(inventory['InventoryDate']).replace(tzinfo=pytz.utc)
                item = domain.put_attributes("%s" % (d,), inventory)

            if ((datetime.datetime.utcnow().replace(tzinfo=pytz.utc) - d).days > 1):
                gv.retrieve_inventory(format="JSON")

            render_inventory(inventory)
        else:
            job = gv.retrieve_inventory(format="JSON")
    except Exception, e:
        print "exception: ", e
        print json.loads(e[1])['message']

def main():
    program_description = u"""
    Command line interface for Amazon Glacier
    """

    # Config parser
    conf_parser = argparse.ArgumentParser(
                                formatter_class=argparse.ArgumentDefaultsHelpFormatter,
                                add_help=False)

    conf_parser.add_argument("-c", "--conf", default=".glacier",
                        help="Specify config file", metavar="FILE")
    args, remaining_argv = conf_parser.parse_known_args()

    # Here we parse config from files in home folder or in current folder
    # We use separate sections for aws and glacier speciffic configs
    aws = glacier = {}
    config = ConfigParser.SafeConfigParser()
    if config.read([args.conf, os.path.expanduser('~/.glacier')]):
        try:
            aws = dict(config.items("aws"))
        except ConfigParser.NoSectionError:
            pass
        try:
            glacier = dict(config.items("glacier"))
        except ConfigParser.NoSectionError:
            pass

    # Join config options with environemnts
    aws= dict(os.environ.items() + aws.items() )
    glacier= dict(os.environ.items() + glacier.items() )

    # Helper functions
    filt_s= lambda x: x.lower().replace("_","-")
    filt = lambda x,y="": dict(((y+"-" if y not in filt_s(k) else "") +
                             filt_s(k), v) for (k, v) in x.iteritems())
    a_required = lambda x: x not in filt(aws,"aws")
    required = lambda x: x not in filt(glacier)
    a_default = lambda x: filt(aws, "aws").get(x)
    default = lambda x: filt(glacier).get(x)

    # Main parser
    parser = argparse.ArgumentParser(parents=[conf_parser],
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter,
                                     description=program_description)
    subparsers = parser.add_subparsers(title='Subcommands',
                                       help=u"For subcommand help, use: glacier <subcommand> -h")

    group = parser.add_argument_group('aws')
    help_msg_config = u"(Required if you haven't created .glacier config file)"
    group.add_argument('--aws-access-key',
                        required= a_required("aws-access-key"),
                        default= a_default("aws-access-key"),
                        help="Your aws access key " + help_msg_config)
    group.add_argument('--aws-secret-key',
                        required=a_required("aws-secret-key"),
                        default=a_default("aws-secret-key"),
                        help="Your aws secret key " + help_msg_config)
    group = parser.add_argument_group('glacier')
    group.add_argument('--region',
                        required=required("region"),
                        default=default("region"),
                        help="Region where glacier should take action " + help_msg_config)
    group.add_argument('--bookkeeping',
                        required= False,
                        default= default("bookkeeping") and True,
                        action= "store_true",
                        help="Should we keep book of all creatated archives.\
                              This requires a SimpleDB account and it's \
                              bookkeeping domain name set")
    group.add_argument('--bookkeeping-domain-name',
                        required= False,
                        default= default("bookkeeping-domain-name"),
                        help="SimpleDB domain name for bookkeeping.")

    parser_lsvault = subparsers.add_parser("lsvault", help="List vaults")
    parser_lsvault.set_defaults(func=lsvault)

    parser_mkvault = subparsers.add_parser("mkvault", help="Create a new vault")
    parser_mkvault.add_argument('vault')
    parser_mkvault.set_defaults(func=mkvault)

    parser_rmvault = subparsers.add_parser('rmvault', help='Remove vault')
    parser_rmvault.add_argument('vault')
    parser_rmvault.set_defaults(func=rmvault)

    parser_listjobs = subparsers.add_parser('listjobs', help='List jobs')
    parser_listjobs.add_argument('vault')
    parser_listjobs.set_defaults(func=listjobs)

    parser_describejob = subparsers.add_parser('describejob', help='Describe job')
    parser_describejob.add_argument('vault')
    parser_describejob.add_argument('jobid')
    parser_describejob.set_defaults(func=describejob)

    parser_upload = subparsers.add_parser('upload', help='Upload an archive',
                               formatter_class=argparse.RawTextHelpFormatter)
    parser_upload.add_argument('vault')
    parser_upload.add_argument('filename')
    parser_upload.add_argument('--stdin',
                                help="Input data from stdin, instead of file",
                                action='store_true')
    parser_upload.add_argument('--name', default=None,
                                help='''\
Use the given name as the filename for bookkeeping
purposes. This option is useful in conjunction with
--stdin or when the file being uploaded is a
temporary file.''')
    parser_upload.add_argument('--partsize', type=int, default=-1,
                               help='''\
Part size to use for upload (in Mb). Must
be a power of 2 in the range:
    1 .. 4,294,967,296 (2^0 .. 2^32).
Values that are not a power of 2 will be
adjusted upwards to the next power of 2.

Amazon accepts up to 10,000 parts per upload.

Smaller parts result in more frequent progress
updates, and less bandwidth wasted if a part
needs to be re-transmitted. On the other hand,
smaller parts limit the size of the archive that
can be uploaded. Some examples:

partsize  MaxArchiveSize
    1        1*1024*1024*10000 ~= 10Gb
    4        4*1024*1024*10000 ~= 41Gb
   16       16*1024*1024*10000 ~= 137Gb
  128      128*1024*1024*10000 ~= 1.3Tb

By default, the smallest possible value is used
when the archive size is known ahead of time.
Otherwise (when reading from STDIN) a value of
128 is used.''')
    parser_upload.add_argument('description', nargs='*')
    parser_upload.set_defaults(func=putarchive)

    parser_getarchive = subparsers.add_parser('getarchive',
                help='Get a file by explicitly setting archive id')
    parser_getarchive.add_argument('vault')
    parser_getarchive.add_argument('archive')
    parser_getarchive.add_argument('filename', nargs='?')
    parser_getarchive.set_defaults(func=getarchive)

    parser_rmarchive = subparsers.add_parser('rmarchive', help='Remove archive')
    parser_rmarchive.add_argument('vault')
    parser_rmarchive.add_argument('archive')
    parser_rmarchive.set_defaults(func=deletearchive)

    parser_search = subparsers.add_parser('search',
                help='Search SimpleDB database (if it was created). \
                      By default returns contents of vault.')
    parser_search.add_argument('--vault')
    parser_search.add_argument('--search_term')
    parser_search.set_defaults(func=search)

    parser_inventory = subparsers.add_parser('inventory',
                help='List inventory of a vault')
    parser_inventory.add_argument('--force', action='store_true',
                                 help="Create a new inventory job")
    parser_inventory.add_argument('vault')
    parser_inventory.set_defaults(func=inventory)

    parser_describevault = subparsers.add_parser('describevault', help='Describe vault')
    parser_describevault.add_argument('vault')
    parser_describevault.set_defaults(func=describevault)

    parser_listmultiparts = subparsers.add_parser('listmultiparts', help='List multipart uploads')
    parser_listmultiparts.add_argument('vault')
    parser_listmultiparts.set_defaults(func=listmultiparts)

    parser_abortmultipart = subparsers.add_parser('abortmultipart', help='Abort multipart upload')
    parser_abortmultipart.add_argument('vault')
    parser_abortmultipart.add_argument('uploadId')
    parser_abortmultipart.set_defaults(func=abortmultipart)


    # bookkeeping required
    parser_download = subparsers.add_parser('download',
            help='Download a file by searching through SimpleDB cache for it.')
    parser_download.add_argument('--vault',
            help="Specify the vault in which archive is located.")
    parser_download.add_argument('--out-file')
    parser_download.add_argument('filename', nargs='?')
    parser_download.set_defaults(func=download)

    args = parser.parse_args(remaining_argv)
    args.func(args)

if __name__ == "__main__":
    sys.exit(main())
