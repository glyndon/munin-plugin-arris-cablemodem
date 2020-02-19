#!/usr/bin/env python3
"""
    Copyright 2017-2020

    A Munin 'multigraph' plugin that tracks Arris cablemodem status and WAN performance

    This version self-adjusts between the web interfaces of the
    Arris SB6183; tested on firmware D30CM-OSPREY-2.4.0.1-GA-02-NOSH
    and the
    Arris SB8200; tested on firmware SB8200.0200.174F.311915.NSH.RT.NA

    TODO: (needed?) incorporate backoff logic for speedtest, so it doesn't run too much if the speed stays low
"""

import datetime
import json
import math
import os
import re
import subprocess
import textwrap
import requests
from bs4 import BeautifulSoup

STATEFUL_FILE_DIR_DEFAULT = '.'
SPEEDTEST_JSON_FILE = 'speedtest.json'
SPEEDTEST_MAX_AGE = 54
SPEEDTEST_RETEST_DOWNLOAD = 25000000
SPEEDTEST_RETEST_UPLOAD = 1000000
MODEM_STATUS_URL = 'http://192.168.100.1/' # All Arris modems start here
LATENCY_GATEWAY_HOST = '8.8.4.4'
LATENCY_GATEWAY_CMD = "/usr/sbin/traceroute -n --sim-queries=1 --wait=1 --queries=1 --max-hops="
LATENCY_GATEWAY_HOPS = 2
LATENCY_MEASURE_CMD = "/bin/ping -W 3 -nqc 3 "
report = {}
SPEEDTEST_CMD = "/usr/bin/speedtest-cli --json"
# ===== Inclusions ======
# SPEEDTEST_CMD += "--server 14162"  # ND's server
# SPEEDTEST_CMD += "--server 5025"  # ATT's Cicero, Il server
# SPEEDTEST_CMD += "--server 5114"  # ATT's Detroit server
# SPEEDTEST_CMD += "--server 5115"  # ATT's Indianapolis server
# SPEEDTEST_CMD += "--server 1776"  # Comcast's Chicago server
# ===== Exclusions ======
# SPEEDTEST_CMD += "--exclude 16770"  # Fourway.net server; its upload speed varies weirdly
# SPEEDTEST_CMD += "--exclude 14162"  # ND's server
# ===== Test modes ======
# SPEEDTEST_CMD += "--no-download"  # for testing, reports download as 0
# SPEEDTEST_CMD += "--version"  # for testing, does nothing


def main(args):
    global report

    try:
        dirtyConfig = os.environ['MUNIN_CAP_DIRTYCONFIG'] == '1'  # has to exist and be '1'
    except KeyError:
        dirtyConfig = False

    if not getStatusIntoReport(MODEM_STATUS_URL):  # this call also sets report['model_name']
        return False

    modem_uptime_url = ''
    if 'SB6183' in report['model_name']:
        modem_uptime_url = 'http://192.168.100.1/RgSwInfo.asp'
    if 'SB8200' in report['model_name']:
        modem_uptime_url = 'http://192.168.100.1/cmswinfo.html'

    if not getModemUptime(modem_uptime_url):  # this page's URL varies by modem model
        return False
    latencyValid = getNextHopLatency()
    speedTestDataExist = checkSpeedtestData(args)

    # ==== report emission starts here ====

    testTime = datetime.datetime.fromisoformat(report['speedtest']['timestamp'][:-1])
    print('\nmultigraph wan_speedtest')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title {} [01]: Speedtest
        graph_vlabel Megabits/Second
        graph_category x-wan
        graph_args --lower-limit 0
        graph_scale no
        down.label Download
        down.colour 0066cc
        up.label Upload
        up.colour 44aa99
        distance.label Dist. to 
        """).format(report['model_name']), end="")
        try:
            print(report['speedtest']['server']['sponsor'])
        except KeyError:
            print('server')
        print(textwrap.dedent("""\
        distance.colour aaaaaa
        graph_info Graph of Internet Connection Speed @UTC {}""").format(testTime.strftime('%x %X')))
    if (dirtyConfig or (not 'config' in args)) and  speedTestDataExist:
        downloadspeed = float(report['speedtest']['download'] / 1000000)
        uploadspeed = float(report['speedtest']['upload'] / 1000000)
        # fiddle with the miles so the lines on the graph don't coincide/vary as much
        distance = math.log(max(1, float(report['speedtest']['server']['d']) - 3)) + 10
        print('down.value', downloadspeed)
        print('up.value', uploadspeed)
        print('distance.value', distance)

    print('\nmultigraph wan_ping')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title {} [02]: Latency
        graph_vlabel millliSeconds
        graph_category x-wan
        graph_args --alt-autoscale --upper-limit 33 --lower-limit 0 --rigid --allow-shrink
        latency.colour cc2900
        latency.label Latency for
        """).format(report['model_name']), end="")
        print(LATENCY_GATEWAY_HOPS, "hops")
        # print('latency.min 7')  # an artificial and arbitrary floor, so the graph never spikes to zero
    if (dirtyConfig or (not 'config' in args)) and latencyValid:
        print('latency.value', report['next_hop_latency'])

    print('\nmultigraph wan_downpower')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title {} [03]: Downstream Power
        graph_vlabel dB
        graph_category x-wan
        graph_args --alt-autoscale --lower-limit 4""").format(report['model_name']))
        for chan in report['downpower']:
            print('down-power-ch' + chan + '.label', 'ch' + report['downchan_id'][chan])
    if dirtyConfig or (not 'config' in args):
        for chan in report['downpower']:
            print('down-power-ch' + chan + '.value', report['downpower'][chan])

    print('\nmultigraph wan_downsnr')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title {} [04]: Downstream SNR
        graph_vlabel dB
        graph_category x-wan
        graph_args --alt-autoscale --lower-limit 38
        """).format(report['model_name']), end='')
        for chan in report['downsnr']:
            print('down-snr-ch' + chan + '.label', 'ch' + report['downchan_id'][chan])
    if dirtyConfig or (not 'config' in args):
        for chan in report['downsnr']:
            print('down-snr-ch' + chan + '.value', report['downsnr'][chan])

    print('\nmultigraph wan_uppower')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title {} [07]: Upstream Power
        graph_vlabel dB
        graph_category x-wan
        graph_args --alt-autoscale --lower-limit 40 --upper-limit 48
        """).format(report['model_name']), end='')
        for chan in report['uppower']:
            print('up-power-ch' + chan + '.label', 'ch' + report['upchan_id'][chan])
    if dirtyConfig or (not 'config' in args):
        for chan in report['uppower']:
            print('up-power-ch' + chan + '.value', report['uppower'][chan])

    print('\nmultigraph wan_spread')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title {} [08]: Signal Quality Spread
        graph_vlabel dB
        graph_category x-wan
        graph_args --alt-autoscale --lower-limit 0 --upper-limit 3
        graph_scale no
        downpowerspread.label Downstream Power spread
        downsnrspread.label Downstream SNR spread
        uppowerspread.label Upstream Power spread
        """).format(report['model_name']), end='')
    if dirtyConfig or (not 'config' in args):
        print('downpowerspread.value', report['downpowerspread'])
        print('downsnrspread.value', report['downsnrspread'])
        print('uppowerspread.value', report['uppowerspread'])

    print('\nmultigraph wan_error_corr')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title {} [05]: Downstream Corrected
        graph_vlabel Blocks per Minute
        graph_category x-wan
        graph_args --upper-limit 33 --rigid
        graph_period minute
        graph_scale no
        """).format(report['model_name']), end='')
        for chan in report['corrected_total']:
            print('corrected-total-ch' + chan + '.label', 'ch' + report['downchan_id'][chan])
            print('corrected-total-ch' + chan + '.type', 'DERIVE')
            print('corrected-total-ch' + chan + '.min', '0')
    if dirtyConfig or (not 'config' in args):
        for chan in report['corrected_total']:
            print('corrected-total-ch' + chan + '.value', report['corrected_total'][chan])

    print('\nmultigraph wan_error_uncorr')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title {} [06]: Downstream Uncorrectable
        graph_vlabel Blocks per Minute
        graph_category x-wan
        graph_args --upper-limit 33 --rigid
        graph_period minute
        graph_scale no
        """).format(report['model_name']), end='')
        for chan in report['uncorrectable_total']:
            print('uncorrected-total-ch' + chan + '.label', 'ch' + report['downchan_id'][chan])
            print('uncorrected-total-ch' + chan + '.type', 'DERIVE')
            print('uncorrected-total-ch' + chan + '.min', '0')
    if dirtyConfig or (not 'config' in args):
        for chan in report['uncorrectable_total']:
            print('uncorrected-total-ch' + chan + '.value', report['uncorrectable_total'][chan])

    print('\nmultigraph wan_frequencies')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title {} [09]: Frequency Assignments
        graph_vlabel MHz
        graph_category x-wan
        graph_args --alt-autoscale
        """).format(report['model_name']), end='')
        for chan in report['downfreq']:
            print('downfreq-ch' + chan + '.label', 'dn-ch' + report['downchan_id'][chan])
        for chan in report['upfreq']:
            print('upfreq-ch' + chan + '.label', 'up-ch' + report['upchan_id'][chan])
    if dirtyConfig or (not 'config' in args):
        for chan in report['downfreq']:
            print('downfreq-ch' + chan + '.value', float(report['downfreq'][chan]) / 1000000)
        for chan in report['upfreq']:
            print('upfreq-ch' + chan + '.value', float(report['upfreq'][chan]) / 1000000)

    print('\nmultigraph wan_uptime')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title {} [10]: Uptime
        graph_vlabel uptime in days
        graph_category x-wan
        graph_args --base 1000 --lower-limit 0
        graph_scale no
        uptime.label uptime
        uptime.draw AREA
        """).format(report['model_name']), end='')
    if dirtyConfig or (not 'config' in args):
        print('uptime.value', report['uptime_seconds'])

    return True
    # end main()


def getStatusIntoReport(url):
    global report

    try:
        page = requests.get(url, timeout=25).text
    except requests.exceptions.RequestException:
        print("modem status page not responding", file=sys.stderr)
        return False
    page = page.translate(str.maketrans('', '', "\n\x00\x09\r"))  # drop some nasty characters
    soup = BeautifulSoup(str(page), 'html.parser')

    model_name_tag = soup.find(id='thisModelNumberIs')
    if model_name_tag:
        report['model_name'] = model_name_tag.get_text()
    else:  # If no model # known, we can't continue very well
        return False

    # Be sure WAN is connected, else do not report
    td = soup.find('td', string="DOCSIS Network Access Enabled")
    internetStatus = td.parent()[1].get_text()
    if 'Allowed' not in internetStatus:
        print("# Modem indicates no Internet Connection as of (local time):",
              datetime.datetime.now().isoformat(), file=sys.stderr)
        return False

    # the columnar position of these stats vary between models of modem (why? - seems silly)
    if 'SB6183' in report['model_name']:
        channel_id_col = 3
        downfreq_col = 4
        upfreq_col = 5
        downpower_col = 5
        uppower_col = 6
        downsnr_col = 6
        corrected_col = 7
        uncorrectable_col = 8
    if 'SB8200' in report['model_name']:
        channel_id_col = 0
        downfreq_col = 3
        upfreq_col = 4
        downpower_col = 4
        uppower_col = 6
        downsnr_col = 5
        corrected_col = 6
        uncorrectable_col = 7

    # setup empty dict's for the incoming data rows
    report['downsnr'] = {}
    report['downpower'] = {}
    report['uppower'] = {}
    report['corrected_total'] = {}
    report['uncorrectable_total'] = {}
    report['downchan_id'] = {}
    report['upchan_id'] = {}
    report['downfreq'] = {}
    report['upfreq'] = {}

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

            report['downchan_id'][newRow[0]] = newRow[channel_id_col]
            report['downpower'][newRow[0]] = newRow[downpower_col]
            report['downsnr'][newRow[0]] = newRow[downsnr_col]
            report['downfreq'][newRow[0]] = newRow[downfreq_col]

            report['corrected_total'][newRow[0]] = newRow[corrected_col]
            report['uncorrectable_total'][newRow[0]] = newRow[uncorrectable_col]

    block = soup.find('th', string="Upstream Bonded Channels").parent
    block = block.next_sibling  # skip the header rows
    block = block.next_sibling
    for row in block.next_siblings:
        if isinstance(row, type(block)):
            newRow = []
            for column in row:
                if isinstance(column, type(block)):
                    newRow.append(re.sub("[^0-9.-]", "", column.get_text()))
            report['upchan_id'][newRow[0]] = newRow[channel_id_col]
            report['uppower'][newRow[0]] = newRow[uppower_col]
            report['upfreq'][newRow[0]] = newRow[upfreq_col]

    report['uppowerspread'] = max(float(i) for i in report['uppower'].values()) \
        - min(float(i) for i in report['uppower'].values())
    report['downpowerspread'] = max(float(i) for i in report['downpower'].values()) \
        - min(float(i) for i in report['downpower'].values())
    report['downsnrspread'] = max(float(i) for i in report['downsnr'].values()) \
        - min(float(i) for i in report['downsnr'].values())
    return True


def getModemUptime(url):
    global report

    try:
        page = requests.get(url, timeout=25).text
    except requests.exceptions.RequestException:
        print("modem uptime page not responding", file=sys.stderr)
        return False
    page = page.translate(str.maketrans('', '', "\n\x00\x09\r"))  # drop some nasty characters
    soup = BeautifulSoup(str(page), 'html.parser')  # this call takes a long time

    block = soup.find('td', string="Up Time")
    block = block.next_sibling  # skip the header rows
    block = block.next_sibling
    uptimeText = block.get_text()
    uptimeElements = re.findall(r"\d+", uptimeText)
    uptime_seconds = \
          int(uptimeElements[0]) * 86400 \
        + int(uptimeElements[1]) * 3600 \
        + int(uptimeElements[2]) * 60 \
        + int(uptimeElements[3])
    # report as days, so divide by seconds/day
    report['uptime_seconds'] = float(str(uptime_seconds)) / 86400.0
    return True


    # expected return is that report['gateway'] and report'next_hop_latency'] exist
def getNextHopLatency():
    global report
    report['gateway'] = ''
    report['next_hop_latency'] = ''
    # issue the command to discover the gateway at the designated hop distance
    cmd = LATENCY_GATEWAY_CMD \
        + str(LATENCY_GATEWAY_HOPS) \
        + " " \
        + LATENCY_GATEWAY_HOST
    try:
        output = subprocess.run(cmd.split(' '), capture_output=True)
    except subprocess.CalledProcessError:
        return False
    # parse the results for the IP addr of that hop
    result = ''
    for line in output.stdout.decode("utf-8").split('\n'):
        if line.startswith(' ' + str(LATENCY_GATEWAY_HOPS) + ' '):
            result = line.split(' ')
            if len(result) > 3:
                result = result[3]
            break
    report['gateway'] = str(result)
    # issue the command to measure latency to that hop
    cmd = LATENCY_MEASURE_CMD + report['gateway'] # + " 2>/dev/null"
    try:
        output = result = subprocess.run(cmd.split(' '), capture_output=True)
    except subprocess.CalledProcessError:
        return False
    # parse the results for the 4th field which is the average delay
    result = ''
    for line in output.stdout.decode("utf-8").split('\n'):
        if line.startswith('rtt'):
            fields = line.split('/')
            if len(fields) > 4:
                result = fields[4]
            break
    # clip this value's peaks to spare graph messes when something's wrong
    try:
        if float(result) > 30.0:
            result = str(30.0)
    except ValueError:
        result = ''
    if result is '':
        return False
    report['next_hop_latency'] = str(result)
    return True


def loadSpeedtestFileIntoReport(aFile):
    global report
    report['speedtest'] = {}
    try:
        fhInput = open(aFile, 'r')
        report['speedtest'].update(json.load(fhInput))
        fhInput.close()
        return True
    except (FileNotFoundError, OSError, PermissionError, json.decoder.JSONDecodeError) as the_error:
        print("# error reading", aFile, the_error, file=sys.stderr)
        return False


def checkSpeedtestData(args):
    global SPEEDTEST_JSON_FILE

    try: # Use the munin-supplied folder location, or default for standalone
        SPEEDTEST_JSON_FILE = os.environ['MUNIN_PLUGSTATE'] + '/' + SPEEDTEST_JSON_FILE
    except KeyError:
        SPEEDTEST_JSON_FILE = STATEFUL_FILE_DIR_DEFAULT + '/' + SPEEDTEST_JSON_FILE

    result = loadSpeedtestFileIntoReport(SPEEDTEST_JSON_FILE)
    currentTime = datetime.datetime.utcnow()
    try:
        priorTime = datetime.datetime.fromisoformat(report['speedtest']['timestamp'][:-1])
        minutes_elapsed = (currentTime - priorTime) / datetime.timedelta(minutes=1)
    except KeyError:
        minutes_elapsed = SPEEDTEST_MAX_AGE + 1
    # if it's too old, or recorded a slow test, generate a new one
    if minutes_elapsed > SPEEDTEST_MAX_AGE or \
        ((float(report['speedtest']['download']) < SPEEDTEST_RETEST_DOWNLOAD \
         or float(report['speedtest']['upload']) < SPEEDTEST_RETEST_UPLOAD) \
         and minutes_elapsed > 9): # wait ~10 minutes to retest, so the graph can better show the hiccup
        if not 'nospeedtest' in args: # for testing this code w/o running an actual speedtest
            runSpeedTest(SPEEDTEST_JSON_FILE, SPEEDTEST_CMD)  # then reload our dictionary from the new file
        else:
            print('# would have run:', SPEEDTEST_CMD, file=sys.stderr)
        result = loadSpeedtestFileIntoReport(SPEEDTEST_JSON_FILE)
    return result


def runSpeedTest(output_json_file, speedtest_cmd):
    try:
        outFile = open(output_json_file, 'w')
        result = subprocess.run(speedtest_cmd.split(' '), stdout=outFile)
        outFile.close()
        return result.returncode == 0  # return a boolean
    except (FileNotFoundError, OSError) as the_error:
        print("# error creating:", output_json_file, the_error, file=sys.stderr)


if __name__ == '__main__':
    import sys
    try:
        resultMain = main(sys.argv)
    except (FileNotFoundError, OSError, json.decoder.JSONDecodeError) as the_error:
        print("# error from main():", the_error, file=sys.stderr)
        sys.exit(1)
    sys.exit(0 if resultMain else 1)
