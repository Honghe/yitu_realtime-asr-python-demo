# -*- coding: utf-8 -*-
import logging
import re

logger = logging.getLogger('command')
hdlr = logging.FileHandler('/tmp/command.log')
formatter = logging.Formatter('%(asctime)s %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr)
logger.setLevel(logging.WARN)

# gen patterns
wild_cn = '(.+?)'
numbers = '([一两三四五六七八九十]+?)'
patterns_str = ['上课',
                '下课',
                '给' + wild_cn + '加' + numbers + '分',
                '给' + wild_cn + numbers + '朵小红花',
                '给' + wild_cn + numbers + '颗小星星']
patterns = [re.compile(x) for x in patterns_str]


def command_detect(text):
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            command = match.group()
            # logger.warning('command: {}'.format(command))
            return command
