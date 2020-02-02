#!/usr/bin/env python3
# Copyright 2018 Brad House
# MIT license
# Modified for SB6183 by Glyndon, 2020/2/1

# TODO: Add signal quality spresd, speedtest, and ping-latency graphs
# TODO: Make all the external symbols match the wan-json code,
#       so they can be used intrchangeablly

import html.parser
import os
import re
import urllib.request
import sys
import json


class ArrisHTMLParser(html.parser.HTMLParser):
    state = None
    row = 0
    col = 0
    table_type = None
    result_model = None
    result_uptime = None
    result_downstream = []
    result_upstream = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == 'id' and value == 'thisModelNumberIs':
                self.state = 'model'
        if tag == 'table':
            self.state = 'table'
            self.table_type = None
            self.row = 0
            self.col = 0
        if tag == 'tr':
            self.row = self.row + 1
            self.col = 0
        if tag == 'td':
            self.col = self.col + 1

    def handle_endtag(self, tag):
        if tag == 'table' and self.state == 'table':
            self.state = None

    def handle_data(self, data):
        data = data.strip()
        if data:
            if self.state == 'model':
                self.result_model = data
                self.state = None
            if self.state == 'table' and self.table_type is None and self.row == 1 and self.col == 0:
                if data == 'Downstream Bonded Channels':
                    self.table_type = 'downstream'
                if data == 'Upstream Bonded Channels':
                    self.table_type = 'upstream'
                if data == 'Status':
                    self.table_type = 'status'
            if self.state == 'table' and self.table_type == 'status' and self.row > 1 and self.col > 1:
                self.result_uptime = data
                self.state = None
            if self.state == 'table' and self.table_type == 'downstream' and self.row > 2 and self.col > 0:
                idx = self.row - 3
                if len(self.result_downstream) <= idx:
                    self.result_downstream.append({})
                if self.col == 1: # Channel position
                    self.result_downstream[idx]['channel']               = data
                if self.col == 2: # Lock Status
                    self.result_downstream[idx]['locked']                = data
                if self.col == 3: # Modulation
                    self.result_downstream[idx]['modulation']            = data
                if self.col == 4: # Channel_ID
                    self.result_downstream[idx]['channel_id']            = data
                if self.col == 5: # Frequency
                    self.result_downstream[idx]['frequency_mhz']         = (int)(data.split(" ")[0]) / 1000000
                if self.col == 6: # Power
                    self.result_downstream[idx]['power_dbmv']            = data.split(" ")[0]
                if self.col == 7: # SNR
                    self.result_downstream[idx]['snr_db']                = data.split(" ")[0]
                if self.col == 8: # Corrected, div by 5 for a per-minute rate
                    self.result_downstream[idx]['errors_corrected']      = data
                if self.col == 9: # Uncorrectables, div by 5 for a per-minute rate
                    self.result_downstream[idx]['errors_uncorrectables'] = data
            if self.state == 'table' and self.table_type == 'upstream' and self.row > 2 and self.col > 0:
                idx = self.row - 3
                if len(self.result_upstream) <= idx:
                    self.result_upstream.append({})
                if self.col == 1: # Channel
                    self.result_upstream[idx]['channel'] = data
                if self.col == 2: # Lock Status
                    self.result_upstream[idx]['locked']        = data
                if self.col == 3: # Channel type
                    self.result_upstream[idx]['type']          = data
                if self.col == 4: # Channel ID
                    self.result_upstream[idx]['channel_id']    = data
                if self.col == 5: # Width
                    self.result_upstream[idx]['width_mhz']     = (int)(data.split(" ")[0]) / 1000
                if self.col == 6: # Frequency
                    self.result_upstream[idx]['frequency_mhz'] = (int)(data.split(" ")[0]) / 1000000
                if self.col == 7: # Power
                    self.result_upstream[idx]['power_dbmv']    = data.split(" ")[0]

def parse_url(url):
    try:
        page = urllib.request.urlopen(url, None, 30)
    except:
        return None

    parser = ArrisHTMLParser()
    parser.feed(page.read().decode('utf-8'))

    # Convert into a "nicer" format
    result = {}
    result['model'] = parser.result_model
    result['uptime'] = parser.result_uptime
    result['downstream_channels'] = {}
    result['upstream_channels'] = {}

    for item in parser.result_downstream:
        if item['modulation'] == 'QAM256':
            channel = (int)(item['channel'])
            result['downstream_channels'][channel] = {}
            result['downstream_channels'][channel]['modulation']            = item['modulation']
            result['downstream_channels'][channel]['channel_id']            = item['channel_id']
            result['downstream_channels'][channel]['frequency_mhz']         = item['frequency_mhz']
            result['downstream_channels'][channel]['power_dbmv']            = item['power_dbmv']
            result['downstream_channels'][channel]['snr_db']                = item['snr_db']
            result['downstream_channels'][channel]['errors_corrected']      = item['errors_corrected']
            result['downstream_channels'][channel]['errors_uncorrectables'] = item['errors_uncorrectables']

    for item in parser.result_upstream:
        channel = (int)(item['channel'])
        result['upstream_channels'][channel] = {}
        result['upstream_channels'][channel]['modulation']    = item['type']
        result['upstream_channels'][channel]['locked']        = item['locked']
        result['upstream_channels'][channel]['channel_id']    = item['channel_id']
        result['upstream_channels'][channel]['frequency_mhz'] = item['frequency_mhz']
        result['upstream_channels'][channel]['width_mhz']     = item['width_mhz']
        result['upstream_channels'][channel]['power_dbmv']    = item['power_dbmv']

    return result


# Goal of this function is if we only get partial results back from the cable modem, we
#  still need to have a properly structured tree with the right elements just with no
#  values so configuration information can be output as appropriate at any time.
def merge_result(data):
    isgood = True

    try:
        with open(os.environ['MUNIN_STATEFILE']) as f:
            old_data = json.load(f)
    except:
        old_data = None

    if not data:
        data = {}

    # populate model
    if 'model' not in data:
        if 'model' in old_data:
            data['model'] = old_data['model']
        else:
            data['model'] = 'cablemodem'

    # populate uptime
    if 'uptime' not in data:
        if 'uptime' in old_data:
            data['uptime'] = old_data['uptime']
        else:
            data['uptime'] = '0'

    # populate downstream_channels
    if 'downstream_channels' not in data or not data['downstream_channels']:
        isgood = False
        data['downstream_channels'] = {}
        # Create Data
        if old_data and 'downstream_channels' in old_data:
            for channel in old_data['downstream_channels']:
                channel=(int)(channel)
                data['downstream_channels'][channel]                          = {}
                data['downstream_channels'][channel]['modulation']            = None
                data['downstream_channels'][channel]['channel_id']            = None
                data['downstream_channels'][channel]['frequency_mhz']         = None
                data['downstream_channels'][channel]['power_dbmv']            = None
                data['downstream_channels'][channel]['snr_db']                = None
                data['downstream_channels'][channel]['errors_corrected']      = None
                data['downstream_channels'][channel]['errors_uncorrectables'] = None

    # populate upstream_channels
    if 'upstream_channels' not in data or not data['upstream_channels']:
        isgood = False
        data['upstream_channels'] = {}
        # Create data
        if old_data and 'upstream_channels' in old_data:
            for channel in old_data['upstream_channels']:
                channel=(int)(channel)
                data['upstream_channels'][channel]                  = {}
                data['upstream_channels'][channel]['modulation']    = None
                data['upstream_channels'][channel]['locked']        = None
                data['upstream_channels'][channel]['channel_id']    = None
                data['upstream_channels'][channel]['frequency_mhz'] = None
                data['upstream_channels'][channel]['width_mhz']     = None
                data['upstream_channels'][channel]['power_dbmv']    = None

    # Cache fully good result
    if isgood:
        # print("writing state file")
        with open(os.environ['MUNIN_STATEFILE'], 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)

    return data

def convertUptimeToDays(uptime_string):
    uptimeElements = re.findall(r"\d+", uptime_string)
    uptime_seconds = \
          int(uptimeElements[0]) * 86400 \
        + int(uptimeElements[1]) * 3600 \
        + int(uptimeElements[2]) * 60 \
        + int(uptimeElements[3])
    return str(float(uptime_seconds) / 86400.0)


status_page_raw = parse_url("http://192.168.100.1")
result = merge_result(status_page_raw)
info_page_raw = parse_url("http://192.168.100.1/RgSwInfo.asp")
result = merge_result(info_page_raw)

result['uptime'] = convertUptimeToDays(result['uptime'])

try:
    dirtyConfig = os.environ['MUNIN_CAP_DIRTYCONFIG'] == '1'  # has to exist and be '1'
except KeyError:
    dirtyConfig = False

if 'config' in sys.argv:
    print("multigraph arris_downsnr")
    print("graph_title Arris", result['model'] or 'Modem', "[2] Downstream Signal to Noise (dB)")
    print("graph_vlabel db (decibels)")
    print("graph_category x-wan-arris")
    print("graph_args --alt-autoscale --lower-limit 38")
    # print("update_rate 60")
    for key in sorted(result['downstream_channels']):
        print("downsnr{0}.label Channel {1}".format(key, result['downstream_channels'][key]['channel_id']))
        print("downsnr{0}.warning 33:".format(key))
    print("")

    print("multigraph arris_downfreq")
    print("graph_title Arris", result['model'] or 'Modem', "[6] Downstream Channel frequency")
    print("graph_vlabel MHz")
    print("graph_category x-wan-arris")
    # print("update_rate 60")
    for key in sorted(result['downstream_channels']):
        print("downfreq{0}.label Channel {1}".format(key, result['downstream_channels'][key]['channel_id']))
    print("")

    print("multigraph arris_downpwr")
    print("graph_title Arris", result['model'] or 'Modem', "[1] Downstream Power Level")
    print("graph_vlabel dBmV")
    print("graph_category x-wan-arris")
    print("graph_args --alt-autoscale --lower-limit 4")
    # print("update_rate 60")
    for key in sorted(result['downstream_channels']):
        print("downpwr{0}.label Channel {1}".format(key, result['downstream_channels'][key]['channel_id']))
        print("downpwr{0}.warning -7:8".format(key))
    print("")

    print("multigraph arris_downcorrected")
    print("graph_title Arris", result['model'] or 'Modem', "[3] Downstream Corrected Errors")
    print("graph_vlabel Blocks per Minute")
    print("graph_category x-wan-arris")
    print("graph_scale no")
    print("graph_period minute")
    print("graph_args --upper-limit 33 --rigid")
    # print("update_rate 60")
    for key in sorted(result['downstream_channels']):
        print("downcorrected{0}.label Channel {1}".format(key, result['downstream_channels'][key]['channel_id']))
        print("downcorrected{0}.type DERIVE".format(key))
        print("downcorrected{0}.min 0".format(key))
    print("")

    print("multigraph arris_downuncorrected")
    print("graph_title Arris", result['model'] or 'Modem', "[4] Downstream Uncorrected Errors")
    print("graph_vlabel Blocks per Minute")
    print("graph_category x-wan-arris")
    print("graph_scale no")
    print("graph_period minute")
    print("graph_args --upper-limit 33 --rigid")
    # print("update_rate 60")
    for key in sorted(result['downstream_channels']):
        print("downuncorrected{0}.label Channel {1}".format(key, result['downstream_channels'][key]['channel_id']))
        print("downuncorrected{0}.type DERIVE".format(key))
        print("downuncorrected{0}.min 0".format(key))
    print("")

    print("multigraph arris_uppwr")
    print("graph_title Arris", result['model'] or 'Modem', "[5] Upstream Power")
    print("graph_vlabel dBmV")
    print("graph_category x-wan-arris")
    print("graph_args --alt-autoscale --lower-limit 40 --upper-limit 48")
    # print("update_rate 60")
    for key in sorted(result['upstream_channels']):
        print("uppwr{0}.label Channel {1}".format(key, result['upstream_channels'][key]['channel_id']))
        print("uppwr{0}.warning 35:49".format(key))
    print("")

    print("multigraph arris_upfreq")
    print("graph_title Arris", result['model'] or 'Modem', "[7] Upstream Frequency")
    print("graph_vlabel MHz")
    print("graph_category x-wan-arris")
    # print("update_rate 60")
    for key in sorted(result['upstream_channels']):
        print("upfreq{0}.label Channel {1}".format(key, result['upstream_channels'][key]['channel_id']))
    print("")

    print("multigraph arris_uptime")
    print("graph_title Arris", result['model'] or 'Modem', "[8] Uptime")
    print("graph_vlabel Days")
    print("graph_category x-wan-arris")
    print("graph_args --base 1000 --lower-limit 0")
    print("graph_scale no")
    # print("update_rate 60")
    print("uptime.label Uptime")
    print("uptime.draw AREA")
    print("")

if dirtyConfig or 'config' not in sys.argv:
    print("multigraph arris_downsnr")
    for key in sorted(result['downstream_channels']):
        item=result['downstream_channels'][key]
        print("downsnr{0}.value {1}".format(key, item['snr_db'] or 'U'))
    print("")

    print("multigraph arris_downfreq")
    for key in sorted(result['downstream_channels']):
        item=result['downstream_channels'][key]
        print("downfreq{0}.value {1}".format(key, item['frequency_mhz'] or 'U'))
    print("")

    print("multigraph arris_downpwr")
    for key in sorted(result['downstream_channels']):
        item=result['downstream_channels'][key]
        print("downpwr{0}.value {1}".format(key, item['power_dbmv'] or 'U'))
    print("")

    print("multigraph arris_downcorrected")
    for key in sorted(result['downstream_channels']):
        item=result['downstream_channels'][key]
        print("downcorrected{0}.value {1}".format(key, item['errors_corrected'] or 'U'))
    print("")

    print("multigraph arris_downuncorrected")
    for key in sorted(result['downstream_channels']):
        item=result['downstream_channels'][key]
        print("downuncorrected{0}.value {1}".format(key, item['errors_uncorrectables'] or 'U'))
    print("")

    print("multigraph arris_uppwr")
    for key in sorted(result['upstream_channels']):
        item=result['upstream_channels'][key]
        print("uppwr{0}.value {1}".format(key, item['power_dbmv'] or 'U'))
    print("")

    print("multigraph arris_upfreq")
    for key in sorted(result['upstream_channels']):
        item=result['upstream_channels'][key]
        print("upfreq{0}.value {1}".format(key, item['frequency_mhz'] or 'U'))
    print("")

    print("multigraph arris_uptime")
    print("uptime.value {0}".format(result['uptime']) or 'U')
    print("")
    sys.exit(0)

sys.exit(1)
