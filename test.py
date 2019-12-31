#!/usr/bin/env python3

dicta = {}

def main(args):
    print('in main...')
    thing(dicta)
    print( 'nothing:', dicta)

def thing(d):
    d = {'snow': "cold", 'heat':"welcome"}
    print( 'thing:', dicta)



    # triggers = ['config','up','down']
    # # any(x in a for x in b)
    # # if any(hit in triggers for hit in args):
    # # print ('args:',args)
    # # print('x in triggers', list(x for x in triggers))
    # # print('x in args', list(x for x in args))
    # if not any(x in triggers for x in args):
    #     print('negative trigger')
    # if './test.py' in args:
    #     print('up hit')
    # print(len(args)==1)

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))