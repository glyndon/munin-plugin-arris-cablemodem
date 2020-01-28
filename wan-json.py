#!/usr/bin/env python3
"""
    Copyright 2017-2020 Gary Dobbins <gary@dobbinsonline.org>

    A Munin 'multigraph' plugin that tracks cablemodem status

    This version is specifically attuned to the web interface of the
    Arris SB6183 firmware: D30CM-OSPREY-2.4.0.1-GA-02-NOSH

    TODO: run speedtest-cli from here, when needed

    TODO: recast the structure so that the config output and values output are adjacent
    and a decision about dirtyConfig determines whether to include values with config
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

STATEFUL_FILE_DIR_DEFAULT = '/var/lib/munin-node/plugin-state/munin'
SPEEDTEST_JSON_FILE = 'speedtest.json'
SPEEDTEST_MAX_AGE = 60
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

    # Use the munin-supplied folder location, else a default when testing standalone
    try:
        SPEEDTEST_JSON_FILE = os.environ['MUNIN_PLUGSTATE'] + '/' + SPEEDTEST_JSON_FILE
    except KeyError:
        SPEEDTEST_JSON_FILE = STATEFUL_FILE_DIR_DEFAULT + SPEEDTEST_JSON_FILE

    dirtyConfig = False
    try:
        if os.environ['MUNIN_CAP_DIRTYCONFIG'] == '1':  # has to exist and be '1'
            dirtyConfig = True
    except KeyError:
        pass

    # See if the existing speed data is in need of updating
    speedTestFileExists = loadFileIntoReport(SPEEDTEST_JSON_FILE)
    currentTime = datetime.datetime.utcnow()
    try:
        priorTime = datetime.datetime.fromisoformat(report['timestamp'][:-1])
        minutes_elapsed = (currentTime - priorTime) / datetime.timedelta(minutes=1)
    except KeyError:
        minutes_elapsed = SPEEDTEST_MAX_AGE + 1
    # if it's too old, or slow, generate a new one
    if minutes_elapsed > SPEEDTEST_MAX_AGE \
        or float(report['download']) < SPEEDTEST_RETEST_DOWNLOAD \
        or float(report['upload']) < SPEEDTEST_RETEST_UPLOAD:
        runSpeedTest(SPEEDTEST_JSON_FILE)  # then reload our dictionary from the new file
        speedTestFileExists = loadFileIntoReport(SPEEDTEST_JSON_FILE)

    # scrape the modem, do some math, and print it all
    if not getUptimeIntoReport():  # also a handy check to see if the modem is responding
        return False

    if not getStatusIntoReport():  # this call takes a long time
        return False

    getNextHopLatency()  # measured by ping

    # If there's a 'config' param, then just emit the config report, and end
    if 'config' in args:
        result = emitConfigText()
        if not dirtyConfig:
            return result
            #else fall thru and report the values too

    if speedTestFileExists:
        # read the speed report file and print from it
        print('\nmultigraph wan_speedtest')
        downloadspeed = float(report['download'] / 1000000)
        uploadspeed = float(report['upload'] / 1000000)
        # recompute the miles so the lines on the graph don't coincide so much
        distance = math.log(max(1, float(report['server']['d']) - 3)) + 10
        print('down.value', downloadspeed)
        print('up.value', uploadspeed)
        print('distance.value', distance)

    print('\nmultigraph wan_ping')
    print('latency.value', report['next_hop_latency'])

    print('\nmultigraph wan_downpower')
    for chan in report['downpower']:
        print('down-power-ch' + chan + '.value', report['downpower'][chan])

    print('\nmultigraph wan_downsnr')
    for chan in report['downsnr']:
        print('down-snr-ch' + chan + '.value', report['downsnr'][chan])

    print('\nmultigraph wan_uppower')
    for chan in report['uppower']:
        print('up-power-ch' + chan + '.value', report['uppower'][chan])

    print('\nmultigraph wan_spread')
    print('downpowerspread.value', report['downpowerspread'])
    print('downsnrspread.value', report['downsnrspread'])
    print('uppowerspread.value', report['uppowerspread'])

    print('\nmultigraph wan_error_corr')
    for chan in report['corrected_total']:
        print('corrected-total-ch' + chan + '.value', report['corrected_total'][chan])

    print('\nmultigraph wan_error_uncorr')
    for chan in report['uncorrectable_total']:
        print('uncorrected-total-ch' + chan + '.value', report['uncorrectable_total'][chan])

    print('\nmultigraph wan_uptime')
    # report as days, so divide seconds
    print('uptime.value', float(report['uptime_seconds']) / 86400.0)

    return True
    # end main()

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

    # setup empty dict's for the incoming data rows
    report['downsnr'] = {}
    report['downpower'] = {}
    report['uppower'] = {}
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

def emitConfigText():
    global report, speedTestFileExists

    if speedTestFileExists:
        print("\n" +
              textwrap.dedent("""\
        multigraph wan_speedtest
        graph_category x-wan
        graph_title [1] WAN Speedtest
        graph_args --base 1000 --lower-limit 0 --upper-limit 35 --rigid
        graph_vlabel Megabits/Second
        graph_scale no
        distance.label Dist. to """), end="")
        print(report['server']['sponsor'])
        print(
            textwrap.dedent("""\
        distance.type GAUGE
        distance.draw LINE
        distance.colour aaaaaa
        down.label Download
        down.type GAUGE
        down.draw LINE
        down.colour 0066cc
        up.label Upload
        up.type GAUGE
        up.draw LINE
        up.colour 44aa99
        graph_info Graph of Internet Connection Speed"""))
        #  --slope-mode
        # return True

    print("\n" +
          textwrap.dedent("""\
    multigraph wan_ping
    graph_title [2] WAN Latency
    graph_vlabel millliSeconds
    graph_category x-wan
    graph_args --alt-autoscale --upper-limit 100 --lower-limit 0 --rigid --allow-shrink
    latency.colour cc2900"""))
    getGateway()
    print("latency.label Latency to " + report['gateway'])

    print("\n" +
          textwrap.dedent("""\
    multigraph wan_downpower
    graph_title [3] WAN Downstream Power
    graph_category x-wan
    graph_vlabel dB
    graph_args --alt-autoscale --lower-limit 0 --rigid"""))
    for chan in report['downpower']:
        print('down-power-ch' + chan + '.label', 'ch' + chan)
    # down-power-spread.label Spread
    # graph_args --alt-autoscale-max --upper-limit 10 --lower-limit 0 --rigid
    # graph_scale no

    print("\n" +
          textwrap.dedent("""\
    multigraph wan_downsnr
    graph_title [4] WAN Downstream SNR
    graph_category x-wan
    graph_vlabel dB
    graph_args --alt-autoscale --lower-limit 38 --rigid"""))
    for chan in report['downsnr']:
        print('down-snr-ch' + chan + '.label', 'ch' + chan)
    # down-snr-spread.label Spread(+30)
    # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
    # graph_scale no

    print("\n" +
          textwrap.dedent("""\
    multigraph wan_uppower
    graph_title [5] WAN Upstream Power
    graph_category x-wan
    graph_vlabel dB
    graph_args --alt-autoscale"""))
    for chan in report['uppower']:
        print('up-power-ch' + chan + '.label', 'ch' + chan)
    # up-power-spread.label Spread(+38)
    # graph_args --alt-autoscale --upper-limit 50 --lower-limit 30 --rigid

    print("\n" +
          textwrap.dedent("""\
    multigraph wan_spread
    graph_title [6] Signal Quality Spread
    graph_args --alt-autoscale
    graph_scale no
    graph_vlabel dB
    graph_category x-wan
    downpowerspread.label Downstream Power spread
    downsnrspread.label Downstream SNR spread
    uppowerspread.label Upstream Power spread"""))
    #  --lower-limit 0 --rigid

    print("\n" +
          textwrap.dedent("""\
    multigraph wan_error_corr
    graph_title [7] WAN Downstream Corrected
    graph_period minute
    graph_vlabel Blocks per Minute
    graph_scale no
    graph_category x-wan"""))
    for chan in report['corrected_total']:
        print('corrected-total-ch' + chan + '.label', 'ch' + chan)
        print('corrected-total-ch' + chan + '.type', 'DERIVE')
        print('corrected-total-ch' + chan + '.min', '0')
    # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
    # graph_args --alt-autoscale

    print("\n" +
          textwrap.dedent("""\
    multigraph wan_error_uncorr
    graph_title [8] WAN Downstream Uncorrectable
    graph_period minute
    graph_vlabel Blocks per Minute
    graph_scale no
    graph_category x-wan"""))
    for chan in report['uncorrectable_total']:
        print('uncorrected-total-ch' + chan + '.label', 'ch' + chan)
        print('uncorrected-total-ch' + chan + '.type', 'DERIVE')
        print('uncorrected-total-ch' + chan + '.min', '0')
    # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
    # graph_args --alt-autoscale

    print("\n" +
          textwrap.dedent("""\
    multigraph wan_uptime
    graph_title [9] Modem Uptime
    graph_args --base 1000 --lower-limit 0
    graph_scale no
    graph_vlabel uptime in days
    graph_category x-wan
    uptime.label uptime
    uptime.draw AREA"""))
    return True


def getGateway():  # returns success by setting report['gateway']
    global report
    cmd = LATENCY_GATEWAY_CMD \
        + str(LATENCY_GATEWAY_HOPS) \
        + " " \
        + LATENCY_GATEWAY_HOST
    output = subprocess.check_output(cmd, shell=True).decode("utf-8")
    result = '0'
    for line in output.split('\n'):
        if line.startswith(' ' + str(LATENCY_GATEWAY_HOPS) + ' '):
            result = line.split(' ')
            if len(result) > 3:
                result = result[3]
            break
    report['gateway'] = str(result)


def getNextHopLatency():
    global report
    getGateway()
    cmd = LATENCY_MEASURE_CMD + report['gateway'] + " 2>/dev/null"
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


def loadFileIntoReport(aFile):
    global report
    try:
        fhInput = open(aFile, 'r')
        report.update(json.load(fhInput))
        fhInput.close()
        return True
    except (FileNotFoundError, OSError, json.decoder.JSONDecodeError) as the_error:
        print("# error reading", aFile, the_error, file=sys.stderr)
        # sys.exit(1)
        return False


def runSpeedTest(output_json_file):
    CMD = ["/usr/bin/speedtest-cli"]
    CMD.append("--json")

    # ===== Inclusions ======
    # CMD = CMD + ["--server", "14162"]) # ND's server
    # CMD = CMD + ["--server", "5025"]) # ATT's Cicero, Il server
    # CMD = CMD + ["--server", "5114"]) # ATT's Detroit server
    # CMD = CMD + ["--server", "5115"]) # ATT's Indianapolis server
    # CMD = CMD + ["--server", "1776"]) # Comcast's Chicago server

    # ===== Exclusions ======
    # CMD = CMD + ["--exclude", "16770") # Fourway.net server; its upload speed varies weirdly
    # CMD = CMD + ["--exclude", "14162"] # ND's server

    outFile = open(output_json_file, 'w')
    result = subprocess.run(CMD, stdout=outFile)
    outFile.close()
    return result.returncode == 0  # return a boolean


if __name__ == '__main__':
    import sys
    try:
        resultMain = main(sys.argv)
    except (FileNotFoundError, OSError, json.decoder.JSONDecodeError) as the_error:
        print("# error in main():", the_error, file=sys.stderr)
        sys.exit(1)
    sys.exit(0 if resultMain else 1)
