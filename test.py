#!/usr/bin/env python3

import os

# dicta = {}
# thing = "thing default-global value"

def main(args):
    global thing

    print('in main...')

    try:
        thing = 'no key, this is default'
        thing = os.environ['MUNIN_PLUGSTATE']
        # thing = os.environ['PATH']
    except KeyError:
        # print('exception occurred:', e)
        # thing = 'no key found'
        pass
    print('MUNIN_PLUGSTATE: ', thing)

#     # thing(dicta)
#     # print( 'nothing:', dicta)
#     triggers = ['config','wan-up','down']
#     plugin_nouns = ['config', 'wan-downpower', 'wan-downsnr', 'wan-uppower', 'wan-corrected', 'wan-uncorrectable', 'wan-ping', 'wan-speedtest']

#     # print('any:', any(triggers in x for x in args))
#     # for word in args:
#     #     print('in:',word in triggers)
#     print('args:',list(arg for arg in args))
#     print('nouns:',list(noun for noun in plugin_nouns))
#     print()

#     # print(any(noun in arg for arg in args for noun in plugin_nouns))
#     if any(noun in arg for arg in args for noun in plugin_nouns):
#         print('any: positive trigger')

#     for noun in plugin_nouns:
#         for arg in args:
#             # print('noun:',noun,'arg:',arg)
#             if noun in arg:
#                 print('nest: positive trigger')

#     return

#     if any(t in word for word in args for t in triggers):
#         print('positive trigger')

#     for t in triggers:
#         if any(t in word for word in args):
#             print('hit')

# def thing(d):
#     # d = {'snow': "cold", 'heat':"welcome"}
#     # print( 'thing:', dicta)

#     # # any(x in a for x in b)
#     # # if any(hit in triggers for hit in args):
#     # # print ('args:',args)
#     # # print('x in triggers', list(x for x in triggers))
#     # # print('x in args', list(x for x in args))
#     # if './test.py' in args:
#     #     print('up hit')
#     # print(len(args)==1)
#     pass

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))