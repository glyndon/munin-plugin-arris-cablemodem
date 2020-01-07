#!/usr/bin/env python3
"""
#!/usr/bin/python3
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
import subprocess
import textwrap
import requests
from bs4 import BeautifulSoup

SIGNAL_JSON_FILE = '/tmp/wan.json'
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
# list of all the names by which we might be called, or valid args supplied
plugin_nouns = ['config', 'wan-downpower', 'wan-downsnr', 'wan-uppower', 'wan-uptime',
                'wan-corrected', 'wan-uncorrectable', 'wan-ping', 'wan-speedtest', 'wan-spread']


def main(args):
    global report, priorReport, MINUTES_ELAPSED

    # are any of the plugin_nouns in any of the args?
    # ((( we can't just check len(args)==1, since args[0] might be one of those nouns )))
    if not any(noun in arg for arg in args for noun in plugin_nouns):
        # ============================================================
        # This is the default logic that happens when called by no plugin-noun's name.
        # Instead of reporting we scrape the modem, do some math, and store the JSON

        reportDateTime()  # get current time into the dictionary
        if getUptimeIntoReport():  # also a handy check to see if the modem is responding
            return 1
        try:  # fetch last-run's data and datetime
            fhInput = open(SIGNAL_JSON_FILE, 'r')
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

        if getStatusIntoReport():
            return 1
        getGateway()  # determined by traceroute
        getNextHopLatency()  # measured by ping
        try:  # get all the status data from the modem
            fhOutput = open(SIGNAL_JSON_FILE, 'w')
        except OSError:
            print("something went wrong creating",
                  SIGNAL_JSON_FILE, file=sys.stderr)
            return 1
        json.dump(report, fhOutput, indent=2)
        fhOutput.close()
        return 0

    # If there's a 'config' param, then just emit the relevant static config report, and end
    elif 'config' in args:
        reportConfig(args)
        return 0

    elif any('wan-speedtest' in word for word in args):
        # speedtest's JSON file is generated elsewhere, we just report it to Munin
        openInput(SPEEDTEST_JSON_FILE)
        downloadspeed = float(report['download'] / 1000000)
        uploadspeed = float(report['upload'] / 1000000)
        # recompute the miles so the lines on the graph don't coincide so much
        distance = math.log(max(1, float(report['server']['d']) - 3)) + 10
        print('down.value', downloadspeed)
        print('up.value', uploadspeed)
        print('distance.value', distance)
        return 0

    # everything past here needs report[] filled-in
    openInput(SIGNAL_JSON_FILE)
    # report data as a plugin for the name by which we were called

    if any('wan-downpower' in word for word in args):
        for chan in report['downpower']:
            print('down-power-ch' + chan + '.value', report['downpower'][chan])
        # print('down-power-spread.value', report['downpowerspread'])

    elif any('wan-downsnr' in word for word in args):
        for chan in report['downsnr']:
            print('down-snr-ch' + chan + '.value', report['downsnr'][chan])
        # print('down-snr-spread.value', report['downsnrspread'])

    elif any('wan-uppower' in word for word in args):
        for chan in report['uppower']:
            print('up-power-ch' + chan + '.value', report['uppower'][chan])
        # print('up-power-spread.value', report['uppowerspread'])

    elif any('wan-corrected' in word for word in args):
        try:
            for chan in report['corrected']:
                print('down-corrected-ch' + chan + '.value',
                      report['corrected'][chan])
        except KeyError:  # silently tolerate this section being absent
            pass

    elif any('wan-uncorrectable' in word for word in args):
        try:
            for chan in report['uncorrectable']:
                print('down-uncorrectable-ch' + chan + '.value',
                      report['uncorrectable'][chan])
        except KeyError:  # silently tolerate this section being absent
            pass

    elif any('wan-ping' in word for word in args):
        print('latency.value', report['next_hop_latency'])

    elif any('wan-uptime' in word for word in args):
        # report as days, so divide seconds ...
        print('uptime.value', float(report['uptime_seconds']) / 86400.0)

    elif any('wan-spread' in word for word in args):
        # report as days, so divide seconds ...
        print('downpowerspread.value', report['downpowerspread'])
        print('downsnrspread.value', report['downsnrspread'])
        print('uppowerspread.value', report['uppowerspread'])

    return 0


def getStatusIntoReport():
    global report, priorReport, MINUTES_ELAPSED

    # Get the main page with its various stats
    try:
        page = requests.get(MODEM_STATUS_URL, timeout=25).text
    except requests.exceptions.RequestException:
        print("modem status page not responding", file=sys.stderr)
        return 1
    page = page.replace('\x0D', '')  # strip unwanted newlines
    soup = BeautifulSoup(str(page), 'html5lib')

    # Before parsing all the numbers, be sure WAN is connected, else do not report
    internetStatus = soup.find(
        'td', string="DOCSIS Network Access Enabled").next_sibling.get_text()
    if 'Allowed' not in internetStatus:
        print("Modem indicates no Internet Connection as of (local time):",
              datetime.datetime.now().isoformat(), file=sys.stderr)
        return 1

    # Gather the various data items from the tables...
    block = soup.find('th', string="Downstream Bonded Channels").parent
    block = block.next_sibling  # skip the 2 header rows
    block = block.next_sibling
    report['downsnr'] = {}
    report['downpower'] = {}
    report['uppower'] = {}
    report['corrected'] = {}
    report['uncorrectable'] = {}
    report['corrected-total'] = {}
    report['uncorrectable-total'] = {}

    for row in block.next_siblings:
        if isinstance(row, type(block)):
            newRow = []
            for column in row:  # grab all the row's numbers into a list
                if isinstance(column, type(block)):
                    newRow.append(re.sub("[^0-9.-]", "", column.get_text()))

            report['downpower'][newRow[0]] = newRow[5]
            report['downsnr'][newRow[0]] = newRow[6]

            report['corrected-total'][newRow[0]] = newRow[7]
            report['uncorrectable-total'][newRow[0]] = newRow[8]
            if MINUTES_ELAPSED > 1 and 'corrected-total' in priorReport:
                try:
                    perMinute = (float(newRow[7])
                             - float(priorReport['corrected-total'][newRow[0]])) \
                            / MINUTES_ELAPSED
                except KeyError:  # silently tolerate this section being absent
                    perMinute = 0
                report['corrected'][newRow[0]] = str(max(perMinute, 0))
            if MINUTES_ELAPSED > 1 and 'uncorrectable-total' in priorReport:
                try:
                    perMinute = (float(newRow[8])
                             - float(priorReport['uncorrectable-total'][newRow[0]])) \
                            / MINUTES_ELAPSED
                except KeyError:  # silently tolerate this section being absent
                    perMinute = 0
                report['uncorrectable'][newRow[0]] = str(max(perMinute, 0))

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

    return 0


def getUptimeIntoReport():
    global report, priorReport, MINUTES_ELAPSED

    # Get the 'Up Time' quantity
    try:
        page = requests.get(MODEM_UPTIME_URL, timeout=25).text
    except requests.exceptions.RequestException:
        print("modem uptime page not responding", file=sys.stderr)
        return 1
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
    return 0


def reportConfig(args):
    openInput(SIGNAL_JSON_FILE)

    if any('wan-downpower' in word for word in args):
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

    elif any('wan-downsnr' in word for word in args):
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

    elif any('wan-corrected' in word for word in args):
        print(
            textwrap.dedent("""\
        graph_title [7] WAN Downstream Corrected
        graph_category x-wan
        graph_scale no
        graph_vlabel Blocks per Minute
        graph_args --alt-autoscale
        """))
        # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
        # graph_scale no
        for chan in report['corrected']:
            print('down-corrected-ch' + chan + '.label', 'ch' + chan)

    elif any('wan-uncorrectable' in word for word in args):
        print(
            textwrap.dedent("""\
        graph_title [8] WAN Downstream Uncorrectable
        graph_category x-wan
        graph_scale no
        graph_vlabel Blocks per Minute
        graph_args --alt-autoscale
        """))
        # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
        # graph_scale no
        for chan in report['uncorrectable']:
            print('down-uncorrectable-ch' + chan + '.label', 'ch' + chan)

    elif any('wan-uppower' in word for word in args):
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

    elif any('wan-ping' in word for word in args):
        print(
            textwrap.dedent("""\
        graph_title [2] WAN Next-Hop latency
        graph_vlabel millliSeconds
        graph_category x-wan
        graph_args --alt-autoscale --upper-limit 100 --lower-limit 0 --rigid --allow-shrink
        latency.label Next-Hop
        latency.colour cc2900
        """))

    elif any('wan-speedtest' in word for word in args):
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

    elif any('wan-uptime' in word for word in args):
        print(
            textwrap.dedent("""\
        graph_title [9] Modem Uptime
        graph_args --base 1000 --lower-limit 0
        graph_scale no
        graph_vlabel uptime in days
        graph_category x-wan
        uptime.label uptime
        uptime.draw AREA
        """))

    elif any('wan-spread' in word for word in args):
        print(
            textwrap.dedent("""\
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


def getGateway():  # returns success by setting report['gateway']
    global report, priorReport
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
    global report, priorReport
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
    global report, priorReport
    # utc_offset_sec = time.altzone if time.localtime().tm_isdst else time.timezone
    # utc_offset = datetime.timedelta(seconds=-utc_offset_sec)
    # report['datetime'] = datetime.datetime.now().replace(
    #   tzinfo=datetime.timezone(offset=utc_offset),microsecond=0).isoformat()
    report['datetime_utc'] = datetime.datetime.utcnow().isoformat()


# def getfloat(astr): #for when a string might have other text surrounding a float
#     return str(float( re.findall(r"[-+]?\d*\.\d+|\d+", astr )[0]))


def openInput(aFile):
    global report, priorReport
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
