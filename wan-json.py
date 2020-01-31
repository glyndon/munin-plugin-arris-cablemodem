#!/usr/bin/env python3
"""
    Copyright 2017-2020 Gary Dobbins <gary@dobbinsonline.org>

    A Munin 'multigraph' plugin that tracks cablemodem status

    This version is specifically attuned to the web interface of the
    Arris SB6183 firmware: D30CM-OSPREY-2.4.0.1-GA-02-NOSH

    TODO: try capping speedtest so it doesn't runaway if the speed stays low
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
MODEM_STATUS_URL = 'http://192.168.100.1/'
MODEM_UPTIME_URL = 'http://192.168.100.1/RgSwInfo.asp'
LATENCY_GATEWAY_HOPS = 3
LATENCY_GATEWAY_HOST = '8.8.4.4'
LATENCY_GATEWAY_CMD = "/usr/sbin/traceroute -n --sim-queries=1 --wait=1 --queries=1 --max-hops="
LATENCY_MEASURE_CMD = "/bin/ping -W 3 -nqc 3 "

report = {}
speedTestFileExists = False

def main(args):
    global report, SPEEDTEST_JSON_FILE, speedTestFileExists

    dirtyConfig = False
    try:
        if os.environ['MUNIN_CAP_DIRTYCONFIG'] == '1':  # has to exist and be '1'
            dirtyConfig = True
    except KeyError:
        pass

    # scrape the modem's status pages
    if not getUptimeIntoReport():  # also a handy check to see if the modem is responding
        return False

    if not getStatusIntoReport():  # this call takes a long time, parsing a lot of HTML
        return False

    # ==== report emission starts here ====

    print('\nmultigraph wan_speedtest')
    # See if the existing speed data is in need of updating
    checkSpeedtestData(args)
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title [1] WAN Speedtest
        graph_vlabel Megabits/Second
        graph_category x-wan
        graph_args --base 1000 --lower-limit 0 --upper-limit 35 --rigid
        graph_scale no
        down.label Download
        down.colour 0066cc
        up.label Upload
        up.colour 44aa99
        distance.label Dist. to """), end="")
        try:
            print(report['server']['sponsor'])
        except KeyError:
            print('server')
        print(textwrap.dedent("""\
        distance.colour aaaaaa
        graph_info Graph of Internet Connection Speed"""))
    if (dirtyConfig or (not 'config' in args)) and  speedTestFileExists:
        downloadspeed = float(report['download'] / 1000000)
        uploadspeed = float(report['upload'] / 1000000)
        # fiddle with the miles so the lines on the graph don't coincide/vary as much
        distance = math.log(max(1, float(report['server']['d']) - 3)) + 10
        print('down.value', downloadspeed)
        print('up.value', uploadspeed)
        print('distance.value', distance)

    print('\nmultigraph wan_ping')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title [2] WAN Latency
        graph_vlabel millliSeconds
        graph_category x-wan
        graph_args --alt-autoscale --upper-limit 100 --lower-limit 0 --rigid --allow-shrink
        latency.colour cc2900
        latency.label Latency for """), end="")
        print(LATENCY_GATEWAY_HOPS, "hops")
    if (dirtyConfig or (not 'config' in args)) \
            and getNextHopLatency():
        print('latency.value', report['next_hop_latency'])

    print('\nmultigraph wan_downpower')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title [3] WAN Downstream Power
        graph_vlabel dB
        graph_category x-wan
        graph_args --alt-autoscale --lower-limit 0"""))
        for chan in report['downpower']:
            print('down-power-ch' + chan + '.label', 'ch' + report['downchannel'][chan])
    if dirtyConfig or (not 'config' in args):
        for chan in report['downpower']:
            print('down-power-ch' + chan + '.value', report['downpower'][chan])

    print('\nmultigraph wan_downsnr')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title [4] WAN Downstream SNR
        graph_vlabel dB
        graph_category x-wan
        graph_args --alt-autoscale --lower-limit 33"""))
        for chan in report['downsnr']:
            print('down-snr-ch' + chan + '.label', 'ch' + report['downchannel'][chan])
    if dirtyConfig or (not 'config' in args):
        for chan in report['downsnr']:
            print('down-snr-ch' + chan + '.value', report['downsnr'][chan])

    print('\nmultigraph wan_uppower')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title [7] WAN Upstream Power
        graph_vlabel dB
        graph_category x-wan
        graph_args --alt-autoscale --lower-limit 40 --upper-limit 48"""))
        for chan in report['uppower']:
            print('up-power-ch' + chan + '.label', 'ch' + report['upchannel'][chan])
    if dirtyConfig or (not 'config' in args):
        for chan in report['uppower']:
            print('up-power-ch' + chan + '.value', report['uppower'][chan])

    print('\nmultigraph wan_spread')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title [8] Signal Quality Spread
        graph_vlabel dB
        graph_category x-wan
        graph_args --alt-autoscale --lower-limit 0 --upper-limit 3
        graph_scale no
        downpowerspread.label Downstream Power spread
        downsnrspread.label Downstream SNR spread
        uppowerspread.label Upstream Power spread"""))
    if dirtyConfig or (not 'config' in args):
        print('downpowerspread.value', report['downpowerspread'])
        print('downsnrspread.value', report['downsnrspread'])
        print('uppowerspread.value', report['uppowerspread'])

    print('\nmultigraph wan_error_corr')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title [5] WAN Downstream Corrected
        graph_vlabel Blocks per Minute
        graph_category x-wan
        graph_args --upper-limit 100 --rigid
        graph_period minute
        graph_scale no"""))
        for chan in report['corrected_total']:
            print('corrected-total-ch' + chan + '.label', 'ch' + report['downchannel'][chan])
            print('corrected-total-ch' + chan + '.type', 'DERIVE')
            print('corrected-total-ch' + chan + '.min', '0')
    if dirtyConfig or (not 'config' in args):
        for chan in report['corrected_total']:
            print('corrected-total-ch' + chan + '.value', report['corrected_total'][chan])

    print('\nmultigraph wan_error_uncorr')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title [6] WAN Downstream Uncorrectable
        graph_vlabel Blocks per Minute
        graph_category x-wan
        graph_period minute
        graph_scale no"""))
        for chan in report['uncorrectable_total']:
            print('uncorrected-total-ch' + chan + '.label', 'ch' + report['downchannel'][chan])
            print('uncorrected-total-ch' + chan + '.type', 'DERIVE')
            print('uncorrected-total-ch' + chan + '.min', '0')
    if dirtyConfig or (not 'config' in args):
        for chan in report['uncorrectable_total']:
            print('uncorrected-total-ch' + chan + '.value', report['uncorrectable_total'][chan])

    print('\nmultigraph wan_uptime')
    if 'config' in args:
        print(textwrap.dedent("""\
        graph_title [9] Modem Uptime
        graph_vlabel uptime in days
        graph_category x-wan
        graph_args --base 1000 --lower-limit 0
        graph_scale no
        uptime.label uptime
        uptime.draw AREA"""))
    if dirtyConfig or (not 'config' in args):
        # report as days, so divide by seconds/day
        print('uptime.value', float(report['uptime_seconds']) / 86400.0)

    return True
    # end main()


def getStatusIntoReport():
    global report

    try:
       page = requests.get(MODEM_STATUS_URL, timeout=25).text
    except requests.exceptions.RequestException:
        print("modem status page not responding", file=sys.stderr)
        return False
    page = page.replace('\x0D', '')  # strip unwanted newlines
    soup = BeautifulSoup(str(page), 'html5lib')

    # Before parsing all the numbers, be sure WAN is connected, else do not report
    td = soup.find('td', string="DOCSIS Network Access Enabled")
    internetStatus = td.next_sibling.get_text()
    if 'Allowed' not in internetStatus:
        print("# Modem indicates no Internet Connection as of (local time):",
              datetime.datetime.now().isoformat(), file=sys.stderr)
        return False

    # setup empty dict's for the incoming data rows
    report['downsnr'] = {}
    report['downpower'] = {}
    report['uppower'] = {}
    report['corrected_total'] = {}
    report['uncorrectable_total'] = {}
    report['downchannel'] = {}
    report['upchannel'] = {}

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

            report['downchannel'][newRow[0]] = newRow[3]
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
            report['upchannel'][newRow[0]] = newRow[3]
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


    # expected return is that report['gateway'] and report'next_hop_latency'] exist
def getNextHopLatency():
    global report
    # issue the command to discover the gateway at the designated hop distance
    cmd = LATENCY_GATEWAY_CMD \
        + str(LATENCY_GATEWAY_HOPS) \
        + " " \
        + LATENCY_GATEWAY_HOST
    try:
        output = result = subprocess.run(cmd.split(' '), capture_output=True)
    except subprocess.CalledProcessError:
        return False
    # parse the results for the IP addr of that hop
    result = '0'
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
    result = '0'
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
        result = '0'
    report['next_hop_latency'] = str(result)
    return True


def loadFileIntoReport(aFile):
    global report
    try:
        fhInput = open(aFile, 'r')
        report.update(json.load(fhInput))
        fhInput.close()
        return True
    except (FileNotFoundError, OSError, PermissionError, json.decoder.JSONDecodeError) as the_error:
        print("# error reading", aFile, the_error, file=sys.stderr)
        return False


def checkSpeedtestData(args):
    global SPEEDTEST_JSON_FILE, speedTestFileExists

    try: # Use the munin-supplied folder location, or default for standalone
        SPEEDTEST_JSON_FILE = os.environ['MUNIN_PLUGSTATE'] + '/' + SPEEDTEST_JSON_FILE
    except KeyError:
        SPEEDTEST_JSON_FILE = STATEFUL_FILE_DIR_DEFAULT + '/' + SPEEDTEST_JSON_FILE

    speedTestFileExists = loadFileIntoReport(SPEEDTEST_JSON_FILE)
    currentTime = datetime.datetime.utcnow()
    try:
        priorTime = datetime.datetime.fromisoformat(report['timestamp'][:-1])
        minutes_elapsed = (currentTime - priorTime) / datetime.timedelta(minutes=1)
    except KeyError:
        minutes_elapsed = SPEEDTEST_MAX_AGE + 1
    # if it's too old, or recorded a slow test, generate a new one
    if minutes_elapsed > SPEEDTEST_MAX_AGE \
        or float(report['download']) < SPEEDTEST_RETEST_DOWNLOAD \
        or float(report['upload']) < SPEEDTEST_RETEST_UPLOAD:
        if not 'nospeedtest' in args: # to facilitate testing w/o running an actual test
            runSpeedTest(SPEEDTEST_JSON_FILE)  # then reload our dictionary from the new file
        speedTestFileExists = loadFileIntoReport(SPEEDTEST_JSON_FILE)


def runSpeedTest(output_json_file):
    cmd = "/usr/bin/speedtest-cli --json"

    # ===== Inclusions ======
    # cmd += "--server 14162"  # ND's server
    # cmd += "--server 5025"  # ATT's Cicero, Il server
    # cmd += "--server 5114"  # ATT's Detroit server
    # cmd += "--server 5115"  # ATT's Indianapolis server
    # cmd += "--server 1776"  # Comcast's Chicago server

    # ===== Exclusions ======
    # cmd += "--exclude 16770"  # Fourway.net server; its upload speed varies weirdly
    # cmd += "--exclude 14162"  # ND's server

    # cmd += "--no-download"  # for testing, reports download as 0
    # cmd += "--version"  # for testing, does nothing

    try:
        outFile = open(output_json_file, 'w')
        result = subprocess.run(cmd.split(' '), stdout=outFile)
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
