#!/usr/bin/python3
"""
    Copyright 2017-2019 Gary Dobbins <gary@dobbinsonline.org>

    A Munin plugin that acts like several plugins (each is a uniquely-named link to this file)
    Operates in 3 modes: gather data, report as plugin, report config as plugin
    1) When called by its own name (i.e. by cron), it scrapes data
       from the Arris Cablemodem's status pages and stores the relevant values as a JSON file.
    2) When called by (arg[0]) the name of a plugin it emulates it reads the JSON file
       and reports the requested values.
    3) If 'config' is an arg, reports that plugin's config text.

    Munin calls us through symlinks whose names indicate what plugin Munin thinks it's calling
    We discern this from args[0], which will tell us what plugin to impersonate and report as.

    This version is attuned to the web interface of the Arris SB6183
"""

import datetime
import json
import math
import re
import requests
import subprocess
import textwrap
# import urllib.request
from bs4 import BeautifulSoup

JSON_FILE = '/tmp/wan.json'
SPEEDTEST_JSON_FILE = '/tmp/speedtest.json'
MINUTES_ELAPSED = 0.0
MODEM_STATUS_URL = 'http://192.168.100.1/'
MODEM_UPTIME_URL = 'http://192.168.100.1/RgSwInfo.asp'
LATENCY_TEST_CMD = (
    "/usr/sbin/traceroute "
    "-n --sendwait=0.5 --sim-queries=1 --wait=1 --queries=1 --max-hops=")
LATENCY_TEST_HOST = '8.8.4.4'
LATENCY_TEST_HOPS = 3
report = {}
priorReport = {}


def main(args):
    global report, priorReport, MINUTES_ELAPSED

    # If there's a 'config' param, then just emit the relevant static config report
    if any('config' in word for word in args):
        reportConfig(args)

    # report data as a plugin for the name by which we were called
    elif any('downpower' in word for word in args):
        openInput(JSON_FILE)
        for chan in report['downpower']:
            print('down-power-ch' + chan + '.value', report['downpower'][chan])
        # print('down-power-spread.value', report['downpowerspread'])

    elif any('downsnr' in word for word in args):
        openInput(JSON_FILE)
        for chan in report['downsnr']:
            print('down-snr-ch' + chan + '.value', report['downsnr'][chan])
        # print('down-snr-spread.value', report['downsnrspread'])

    elif any('uppower' in word for word in args):
        openInput(JSON_FILE)
        for chan in report['uppower']:
            print('up-power-ch' + chan + '.value', report['uppower'][chan])
        # print('up-power-spread.value', report['uppowerspread'])

    elif any('corrected' in word for word in args):
        openInput(JSON_FILE)
        try:
            for chan in report['corrected']:
                print('down-corrected-ch' + chan + '.value',
                      report['corrected'][chan])
        except KeyError:  # silently tolerate this section being absent
            pass

    elif any('uncorrectable' in word for word in args):
        openInput(JSON_FILE)
        try:
            for chan in report['uncorrectable']:
                print('down-uncorrectable-ch' + chan + '.value',
                      report['uncorrectable'][chan])
        except KeyError:  # silently tolerate this section being absent
            pass

    elif any('ping' in word for word in args):
        openInput(JSON_FILE)
        print('latency.value', report['next_hop_latency'])

    elif any('speedtest' in word for word in args):
        openInput(SPEEDTEST_JSON_FILE)
        downloadspeed = float(report['download'] / 1000000)
        uploadspeed = float(report['upload'] / 1000000)
        distance = math.log(
            max(1,
                float(report['server']['d']) - 3)
        ) + 10  # recompute the miles so the lines on the graph don't coincide so much
        print('down.value', downloadspeed)
        print('up.value', uploadspeed)
        print('distance.value', distance)

    else:
        # ============================================================
        # in main()... This is the default logic that happens when called to update stored data
        # instead of reporting we scrape the modem, do some math and store the JSON

        reportDateTime()  # get current time into the dictionary
        try:  # fetch last-run's data and datetime
            fhInput = open(JSON_FILE, 'r')
            priorReport = json.load(fhInput)
            fhInput.close()

            # find the distance in time from when we last ran
            priorTime = datetime.datetime.fromisoformat(
                priorReport['datetime_utc'])
            currentTime = datetime.datetime.fromisoformat(
                report['datetime_utc'])
            MINUTES_ELAPSED = (
                currentTime - priorTime) / datetime.timedelta(minutes=1)
        except (FileNotFoundError, OSError, json.decoder.JSONDecodeError):
            MINUTES_ELAPSED = 0

        report['minutes_since_last_run'] = str(MINUTES_ELAPSED)
        try:  # get all the status data from the modem
            fhOutput = open(JSON_FILE, 'w')
        except OSError:
            print("something went wrong creating", JSON_FILE)
            return -1
        if scrapeIntoReport() != 0:
            print("No Internet Connection as of (local time):")
            print(datetime.datetime.now().isoformat())
        else:
            getGateway()  # determined by traceroute
            nextHopLatency()  # measured by ping
        json.dump(report, fhOutput, indent=2)
        fhOutput.close()


def scrapeIntoReport():
    global report

    # Get the 'Up Time' quantity
    try:
        page = requests.get(MODEM_UPTIME_URL, timeout=10).text
    except requests.exceptions.RequestException:
        return 1
    # page = urllib.request.urlopen(MODEM_UPTIME_URL, timeout=2).read()
    # page = page.decode("utf-8")  # convert bytes to str
    page = page.replace('\x0D', '')  # strip unwanted newlines
    soup = BeautifulSoup(str(page),
                         'html.parser')  # this call takes a lot of time

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

    # Get the main page with its various stats
    try:
        page = requests.get(MODEM_STATUS_URL, timeout=10).text
    except requests.exceptions.RequestException:
        return 1
    # page = urllib.request.urlopen(MODEM_STATUS_URL, timeout=2).read()
    # page = page.decode("utf-8")  # convert bytes to str
    page = page.replace('\x0D', '')  # strip unwanted newlines
    soup = BeautifulSoup(str(page),
                         'html.parser')  # this call takes a lot of time

    # Before parsing all the numbers, be sure WAN is connected, else do not report
    internetStatus = soup.find(
        'td', string="DOCSIS Network Access Enabled").next_sibling.get_text()
    if 'Allowed' not in internetStatus:
        return 1

    # Gather the various data items...
    block = soup.find('th', string="Downstream Bonded Channels").parent
    block = block.next_sibling  # skip the header rows
    block = block.next_sibling
    report['downsnr'] = {}
    report['downpower'] = {}
    report['uppower'] = {}
    report['corrected'] = {}
    report['uncorrectable'] = {}
    report['corrected-total'] = {}
    report['uncorrectable-total'] = {}
    down_power_highest = 0
    down_power_lowest = 100
    up_power_highest = 0
    up_power_lowest = 100
    down_snr_highest = 0
    down_snr_lowest = 100
    for row in block.next_siblings:
        if isinstance(row, type(block)):
            newRow = []
            for column in row:
                newRow.append(re.sub("[^0-9.]", "", column.get_text()))

            report['downpower'][newRow[0]] = newRow[5]
            if float(newRow[5]) > down_power_highest:
                down_power_highest = float(newRow[5])
            if float(newRow[5]) < down_power_lowest:
                down_power_lowest = float(newRow[5])

            report['downsnr'][newRow[0]] = newRow[6]
            if float(newRow[6]) > down_snr_highest:
                down_snr_highest = float(newRow[6])
            if float(newRow[6]) < down_snr_lowest:
                down_snr_lowest = float(newRow[6])

            report['corrected-total'][newRow[0]] = newRow[7]
            report['uncorrectable-total'][newRow[0]] = newRow[8]
            if MINUTES_ELAPSED > 1:
                report['corrected'][newRow[0]] = str(
                    (float(newRow[7]) -
                     float(priorReport['corrected-total'][newRow[0]])) /
                    MINUTES_ELAPSED)
                if float(
                        report['corrected'][newRow[0]]
                ) < 0:  # in case the modem was restarted, counts got reset
                    report['corrected'][newRow[0]] = '0'
            if MINUTES_ELAPSED > 1:
                report['uncorrectable'][newRow[0]] = str(
                    (float(newRow[8]) -
                     float(priorReport['uncorrectable-total'][newRow[0]])) /
                    MINUTES_ELAPSED)
                if float(
                        report['uncorrectable'][newRow[0]]
                ) < 0:  # in case the modem was restarted, counts got reset
                    report['uncorrectable'][newRow[0]] = '0'

    block = soup.find('th', string="Upstream Bonded Channels").parent
    block = block.next_sibling  # skip the header rows
    block = block.next_sibling
    for row in block.next_siblings:
        if isinstance(row, type(block)):
            newRow = []
            for column in row:
                newRow.append(re.sub("[^0-9.]", "", column.get_text()))
            report['uppower'][newRow[0]] = newRow[6]
            if float(newRow[6]) > up_power_highest:
                up_power_highest = float(newRow[6])
            if float(newRow[6]) < up_power_lowest:
                up_power_lowest = float(newRow[6])

    report['uppowerspread'] = up_power_highest - up_power_lowest
    report['downpowerspread'] = down_power_highest - down_power_lowest
    report['downsnrspread'] = down_snr_highest - down_snr_lowest

    return 0


def reportConfig(args):
    openInput(JSON_FILE)

    if any('downpower' in word for word in args):
        print(
            textwrap.dedent("""\
        graph_title [3] WAN Downstream Power
        graph_category x-wan
        graph_vlabel dB
        graph_args --alt-autoscale
        """))
        # down-power-spread.label Spread
        # graph_args --alt-autoscale-max --upper-limit 10 --lower-limit 0 --rigid
        # graph_scale no
        for chan in report['downpower']:
            print('down-power-ch' + chan + '.label', 'ch' + chan)

    elif any('downsnr' in word for word in args):
        print(
            textwrap.dedent("""\
        graph_title [4] WAN Downstream SNR
        graph_category x-wan
        graph_vlabel dB
        graph_args --alt-autoscale
        """))
        # down-snr-spread.label Spread(+30)
        # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
        # graph_scale no
        for chan in report['downsnr']:
            print('down-snr-ch' + chan + '.label', 'ch' + chan)

    elif any('corrected' in word for word in args):
        print(
            textwrap.dedent("""\
        graph_title [6] WAN Downstream Corrected
        graph_category x-wan
        graph_vlabel Blocks per Minute
        graph_args --alt-autoscale
        """))
        # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
        # graph_scale no
        for chan in report['corrected']:
            print('down-corrected-ch' + chan + '.label', 'ch' + chan)

    elif any('uncorrectable' in word for word in args):
        print(
            textwrap.dedent("""\
        graph_title [7] WAN Downstream Uncorrectable
        graph_category x-wan
        graph_vlabel Blocks per Minute
        graph_args --alt-autoscale
        """))
        # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
        # graph_scale no
        for chan in report['uncorrectable']:
            print('down-uncorrectable-ch' + chan + '.label', 'ch' + chan)

    elif any('uppower' in word for word in args):
        print(
            textwrap.dedent("""\
        graph_title [5] WAN Upstream Power
        graph_category x-wan
        graph_vlabel dB
        graph_args --alt-autoscale
        """))
        # up-power-spread.label Spread(+38)
        # graph_args --alt-autoscale --upper-limit 50 --lower-limit 30 --rigid
        for chan in report['uppower']:
            print('up-power-ch' + chan + '.label', 'ch' + chan)

    elif any('ping' in word for word in args):
        print(
            textwrap.dedent("""\
        graph_title [2] WAN Next-Hop latency
        graph_vlabel millliSeconds
        graph_category x-wan
        graph_args --alt-autoscale --upper-limit 100 --lower-limit 0 --rigid --allow-shrink
        latency.label Next-Hop
        latency.colour cc2900
        """))

    elif any('speedtest' in word for word in args):
        print(
            textwrap.dedent("""\
        graph_category x-wan
        graph_title [1] WAN Speedtest
        graph_args --base 1000 --lower-limit 0 --upper-limit 35 --rigid --slope-mode
        graph_vlabel Megabits/Second
        graph_scale no
        distance.label V-Distance
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
        graph_info Graph of Internet Connection Speed
        """))


def getGateway():  #returns success by setting report['gateway']
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


def nextHopLatency():
    cmd = "/bin/ping -W 3 -nqc 3 " + report['gateway'] + " 2>/dev/null"
    try:
        output = subprocess.check_output(cmd, shell=True).decode("utf-8")
    except subprocess.CalledProcessError:
        report['next_hop_latency'] = 'NaN'
        return 'NaN'
    result = '0'
    for line in output.split('\n'):
        if line.startswith('rtt'):
            result = line.split('/')
            if len(result) > 4:
                result = result[4]
            break
    report['next_hop_latency'] = str(result)

    try:  # clip this value at 100 to spare graph messes when something's wrong
        if float(result) > 100.0:
            result = str(100.0)
    except ValueError:
        result = '0'
    return result


def reportDateTime():
    # utc_offset_sec = time.altzone if time.localtime().tm_isdst else time.timezone
    # utc_offset = datetime.timedelta(seconds=-utc_offset_sec)
    # report['datetime'] = datetime.datetime.now().replace(
    #   tzinfo=datetime.timezone(offset=utc_offset),microsecond=0).isoformat()
    report['datetime_utc'] = datetime.datetime.utcnow().isoformat()


# def getfloat(astr):
#     return str(float( re.findall(r"[-+]?\d*\.\d+|\d+", astr )[0]))


def openInput(aFile):
    global report, priorReport
    try:
        fhInput = open(aFile, 'r')
        report = json.load(fhInput)
        fhInput.close()
    except (FileNotFoundError, OSError) as the_error:
        print("something went wrong opening for read", aFile)
        print("that error was:", the_error)
        sys.exit()


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
