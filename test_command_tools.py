# -*- coding: utf-8 -*-

from command_tools import command_detect


def test_command_detect():
    assert command_detect('a给黄欧林加两分给谁加两分') == '给黄欧林加两分'



