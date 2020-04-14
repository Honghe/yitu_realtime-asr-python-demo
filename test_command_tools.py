# -*- coding: utf-8 -*-

from command_tools import command_detect


def test_command_detect():
    assert command_detect('a给黄栋加两分给谁加两分') == '给黄栋加两分'
    assert command_detect('a给黄栋一朵小红花') == '给黄栋一朵小红花'



