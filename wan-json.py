#!/usr/bin/env python3
"""
#!/usr/bin/python3
    Copyright 2017-2020 Gary Dobbins <gary@dobbinsonline.org>

    A Munin plugin that acts like several plugins (each is a uniquely-named link to this file)
    Operates in 3 modes: gather data, report as plugin, report config as plugin
    1) When called by its own name (i.e. by cron), it scrapes data
       from the Arris Cablemodem's status pages and stores the relevant values as a JSON file.
    2) When called by (args[0]) the name of a plugin it emulates it reads the JSON file
       and reports the requested values.
    3) If 'config' is an arg, reports that plugin's config text.

    Munin calls us through symlinks whose names indicate what plugin Munin thinks it's calling
    We discern this from args[0], which will tell us what plugin to impersonate and report as.

    This version is attuned to the web interface of the Arris SB6183

    TODO: determine if this 'multigraph' approach works
    TODO:
    Restructure this to store its state at the location supplied by Munin at runtime, using the following environment variables.
    MUNIN_PLUGSTATE: directory to be used for storing files that should be accessed by other plugins
    MUNIN_STATEFILE: single state file to be used by a plugin that wants to track its state from the last time it was requested by the same master
    Source: http://guide.munin-monitoring.org/en/latest/develop/plugins/advanced-topics.html#storing-the-plugin-s-state

    If this is restructured to create the data file when called as a plugin (instead of by cron), then
    there needs to be a semaphore or mutex so we don't have simultaneous instances trying to refresh an old data file.
    Pseudocode:
        While data file is too old or missing
            get lock?:
                scrape data from modem, refresh data file, close it
            else:
                wait until lock is released
        Proceed to open and read data file ...
"""

import datetime
import json
import math
import re
import subprocess
import textwrap
import requests
from bs4 import BeautifulSoup

SPEEDTEST_JSON_FILE = '/tmp/speedtest.json'
MODEM_STATUS_URL = 'http://192.168.100.1/'
MODEM_UPTIME_URL = 'http://192.168.100.1/RgSwInfo.asp'
LATENCY_TEST_CMD = (
    "/usr/sbin/traceroute -n --sim-queries=1 --wait=1 --queries=1 --max-hops=")
LATENCY_TEST_HOPS = 3
LATENCY_TEST_HOST = '8.8.4.4'
report = {}
# list of all the names by which we might be called, or valid args that may be present
plugin_nouns = ['config', 'wan-downpower', 'wan-downsnr', 'wan-uppower', 'wan-uptime', 
                'wan-error-corr', 'wan-error-uncorr',
                'wan-ping', 'wan-speedtest', 'wan-spread']


def main(args):
    global report

    # If there's a 'config' param, then just emit the relevant static config report, and end
    if 'config' in args:
        reportConfig(args)
        return 0

    # This is the default logic that happens when called by no plugin-noun's name.
    # Instead of reporting we scrape the modem, do some math, and store the JSON

    reportDateTime()  # get current time into the dictionary
    if not getUptimeIntoReport():  # also a handy check to see if the modem is responding
        return 1

    if not getStatusIntoReport():
        return 1
    getNextHopLatency()  # measured by ping

    # everything past here needs report[] filled-in

    print('multigraph wan_ping')
    print('latency.value', report['next_hop_latency'])

    print('multigraph wan_downpower')
    for chan in report['downpower']:
        print('down-power-ch' + chan + '.value', report['downpower'][chan])
    # print('down-power-spread.value', report['downpowerspread'])

    print('multigraph wan_downsnr')
    for chan in report['downsnr']:
        print('down-snr-ch' + chan + '.value', report['downsnr'][chan])
    # print('down-snr-spread.value', report['downsnrspread'])

    print('multigraph wan_uppower')
    for chan in report['uppower']:
        print('up-power-ch' + chan + '.value', report['uppower'][chan])
    # print('up-power-spread.value', report['uppowerspread'])

    print('multigraph wan_spread')
    print('downpowerspread.value', report['downpowerspread'])
    print('downsnrspread.value', report['downsnrspread'])
    print('uppowerspread.value', report['uppowerspread'])

    print('multigraph wan_error_corr')
    for chan in report['corrected_total']:
        print('corrected-total-ch' + chan + '.value', report['corrected_total'][chan])

    print('multigraph wan_error_uncorr')
    for chan in report['uncorrectable_total']:
        print('uncorrected-total-ch' + chan + '.value', report['uncorrectable_total'][chan])

    print('multigraph wan_uptime')
    # report as days, so divide seconds ...
    print('uptime.value', float(report['uptime_seconds']) / 86400.0)

    return 0


def getStatusIntoReport():
    global report

    # Get the main page with its various stats
    try:
        page = requests.get(MODEM_STATUS_URL, timeout=25).text
    except requests.exceptions.RequestException:
        print("modem status page not responding", file=sys.stderr)
        return False
    page = page.replace('\x0D', '')  # strip unwanted newlines
    soup = BeautifulSoup(str(page), 'html5lib')

    # Before parsing all the numbers, be sure WAN is connected, else do not report
    internetStatus = soup.find(
        'td', string="DOCSIS Network Access Enabled").next_sibling.get_text()
    if 'Allowed' not in internetStatus:
        print("Modem indicates no Internet Connection as of (local time):",
              datetime.datetime.now().isoformat(), file=sys.stderr)
        return False

    # setup fresh, empty dict's for the incoming data rows
    report['downsnr'] = {}
    report['downpower'] = {}
    report['uppower'] = {}
    # report['corrected'] = {}
    # report['uncorrectable'] = {}
    report['corrected_total'] = {}
    report['uncorrectable_total'] = {}

    # Gather the various data items from the tables...
    block = soup.find('th', string="Downstream Bonded Channels").parent
    block = block.next_sibling  # skip the 2 header rows
    block = block.next_sibling
    for row in block.next_siblings:
        if isinstance(row, type(block)):
            newRow = []
            for column in row:  # grab all the row's numbers into a list
                if isinstance(column, type(block)):
                    newRow.append(re.sub("[^0-9.-]", "", column.get_text()))

            report['downpower'][newRow[0]] = newRow[5]
            report['downsnr'][newRow[0]] = newRow[6]

            report['corrected_total'][newRow[0]] = newRow[7]
            report['uncorrectable_total'][newRow[0]] = newRow[8]

    block = soup.find('th', string="Upstream Bonded Channels").parent
    block = block.next_sibling  # skip the header rows
    block = block.next_sibling
    for row in block.next_siblings:
        if isinstance(row, type(block)):
            newRow = []
            for column in row:
                if isinstance(column, type(block)):
                    newRow.append(re.sub("[^0-9.-]", "", column.get_text()))
            report['uppower'][newRow[0]] = newRow[6]

    report['uppowerspread'] = max(float(i) for i in report['uppower'].values()) \
        - min(float(i) for i in report['uppower'].values())
    report['downpowerspread'] = max(float(i) for i in report['downpower'].values()) \
        - min(float(i) for i in report['downpower'].values())
    report['downsnrspread'] = max(float(i) for i in report['downsnr'].values()) \
        - min(float(i) for i in report['downsnr'].values())
    return True


def getUptimeIntoReport():
    global report

    # Get the 'Up Time' quantity
    try:
        page = requests.get(MODEM_UPTIME_URL, timeout=25).text
    except requests.exceptions.RequestException:
        print("modem uptime page not responding", file=sys.stderr)
        return False
    page = page.replace('\x0D', '')  # strip unwanted newlines
    soup = BeautifulSoup(str(page), 'html5lib')  # this call takes a long time

    block = soup.find('td', string="Up Time")
    block = block.next_sibling  # skip the header rows
    block = block.next_sibling
    uptimeText = block.get_text()
    uptimeElements = re.findall(r"\d+", uptimeText)
    uptime_seconds = int(uptimeElements[3]) \
        + int(uptimeElements[2]) * 60 \
        + int(uptimeElements[1]) * 3600 \
        + int(uptimeElements[0]) * 86400
    report['uptime_seconds'] = str(uptime_seconds)
    return True


def reportConfig(args):
    if not getStatusIntoReport():
        return 1

    print(
        textwrap.dedent("""\
    multigraph wan_ping
    graph_title [2] WAN Latency
    graph_vlabel millliSeconds
    graph_category x-wan
    graph_args --alt-autoscale --upper-limit 100 --lower-limit 0 --rigid --allow-shrink
    latency.label Latency to target
    latency.colour cc2900
    """))

    print(
        textwrap.dedent("""\
    multigraph wan_downpower
    graph_title [3] WAN Downstream Power
    graph_category x-wan
    graph_vlabel dB
    graph_args --alt-autoscale --lower-limit 0 --rigid
    """))
    for chan in report['downpower']:
        print('down-power-ch' + chan + '.label', 'ch' + chan)
    # down-power-spread.label Spread
    # graph_args --alt-autoscale-max --upper-limit 10 --lower-limit 0 --rigid
    # graph_scale no

    print(
        textwrap.dedent("""\
    multigraph wan_downsnr
    graph_title [4] WAN Downstream SNR
    graph_category x-wan
    graph_vlabel dB
    graph_args --alt-autoscale --lower-limit 38 --rigid
    """))
    for chan in report['downsnr']:
        print('down-snr-ch' + chan + '.label', 'ch' + chan)
    # down-snr-spread.label Spread(+30)
    # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
    # graph_scale no

    print(
        textwrap.dedent("""\
    multigraph wan_uppower
    graph_title [5] WAN Upstream Power
    graph_category x-wan
    graph_vlabel dB
    graph_args --alt-autoscale
    """))
    for chan in report['uppower']:
        print('up-power-ch' + chan + '.label', 'ch' + chan)
    # up-power-spread.label Spread(+38)
    # graph_args --alt-autoscale --upper-limit 50 --lower-limit 30 --rigid

    print(
        textwrap.dedent("""\
    multigraph wan_spread
    graph_title [6] Signal Quality Spread
    graph_args --alt-autoscale
    graph_scale no
    graph_vlabel dB
    graph_category x-wan
    downpowerspread.label Downstream Power spread
    downsnrspread.label Downstream SNR spread
    uppowerspread.label Upstream Power spread
    """))
    #  --lower-limit 0 --rigid

    print(
        textwrap.dedent("""\
    multigraph wan_error_corr
    graph_title [7] WAN Downstream Corrected
    graph_period minute
    graph_vlabel Blocks per Minute
    graph_scale no
    graph_category x-wan
    """))
    for chan in report['corrected_total']:
        print('corrected-total-ch' + chan + '.label', 'ch' + chan)
        print('corrected-total-ch' + chan + '.type', 'DERIVE')
        print('corrected-total-ch' + chan + '.min', '0')
    # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
    # graph_args --alt-autoscale

    print(
        textwrap.dedent("""\
    multigraph wan_error_uncorr
    graph_title [8] WAN Downstream Uncorrectable
    graph_period minute
    graph_vlabel Blocks per Minute
    graph_scale no
    graph_category x-wan
    """))
    for chan in report['uncorrectable_total']:
        print('uncorrected-total-ch' + chan + '.label', 'ch' + chan)
        print('uncorrected-total-ch' + chan + '.type', 'DERIVE')
        print('uncorrected-total-ch' + chan + '.min', '0')
    # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
    # graph_args --alt-autoscale

    print(
        textwrap.dedent("""\
    multigraph wan_uptime
    graph_title [9] Modem Uptime
    graph_args --base 1000 --lower-limit 0
    graph_scale no
    graph_vlabel uptime in days
    graph_category x-wan
    uptime.label uptime
    uptime.draw AREA
    """))


def getGateway():  # returns success by setting report['gateway']
    global report
    cmd = LATENCY_TEST_CMD \
        + str(LATENCY_TEST_HOPS) \
        + " " \
        + LATENCY_TEST_HOST
    output = subprocess.check_output(cmd, shell=True).decode("utf-8")
    result = '0'
    for line in output.split('\n'):
        if line.startswith(' ' + str(LATENCY_TEST_HOPS) + ' '):
            result = line.split(' ')
            if len(result) > 3:
                result = result[3]
            break
    report['gateway'] = str(result)


def getNextHopLatency():
    global report
    getGateway()
    cmd = "/bin/ping -W 3 -nqc 3 " + report['gateway'] + " 2>/dev/null"
    # cmd = "/bin/ping -W 3 -nqc 3 " +  LATENCY_TEST_HOST + " 2>/dev/null"
    try:
        output = subprocess.check_output(cmd, shell=True).decode("utf-8")
    except subprocess.CalledProcessError:
        report['next_hop_latency'] = 'NaN'
        return
    result = '0'
    for line in output.split('\n'):
        if line.startswith('rtt'):
            fields = line.split('/')
            if len(fields) > 4:
                result = fields[4]
            break

    try:  # clip this value to spare graph messes when something's wrong
        if float(result) > 30.0:
            result = str(30.0)
    except ValueError:
        result = '0'
    report['next_hop_latency'] = str(result)


def reportDateTime():
    global report
    # utc_offset_sec = time.altzone if time.localtime().tm_isdst else time.timezone
    # utc_offset = datetime.timedelta(seconds=-utc_offset_sec)
    # report['datetime'] = datetime.datetime.now().replace(
    #   tzinfo=datetime.timezone(offset=utc_offset),microsecond=0).isoformat()
    report['datetime_utc'] = datetime.datetime.utcnow().isoformat()


# def getfloat(astr): #for when a string might have other text surrounding a float
    # gets just the first complete number, in case there's more than one
    # return str(float( re.findall(r"[-+]?\d*\.\d+|[-+]?\d+", astr )[0]))


def openInput(aFile):
    global report
    try:
        fhInput = open(aFile, 'r')
        report = json.load(fhInput)
        fhInput.close()
    except (FileNotFoundError, OSError, json.decoder.JSONDecodeError) as the_error:
        print("error reading", aFile, the_error, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    import sys
    try:
        main_result = main(sys.argv)
    except (FileNotFoundError, OSError, json.decoder.JSONDecodeError) as the_error:
        print("error in main():", the_error, file=sys.stderr)
        sys.exit(1)
    sys.exit(main_result)
