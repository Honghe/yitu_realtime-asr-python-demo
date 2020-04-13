# -*- coding: utf-8 -*-
import logging
import re

logger = logging.getLogger('command')
hdlr = logging.FileHandler('/tmp/command.log')
formatter = logging.Formatter('%(asctime)s %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr)
logger.setLevel(logging.WARN)


def command_detect(text):
    patterns_str = ['上课',
                    '下课',
                    '给.+?加.+?分',
                    '给.+?一朵小红花',
                    '给.+?一颗小星星']
    patterns = [re.compile(x) for x in patterns_str]
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            command = match.group()
            logger.warning('command: {}'.format(command))
            return command
