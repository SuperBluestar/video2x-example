#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (C) 2018-2022 K4YT3X and contributors.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

Name: Interpolator
Author: K4YT3X
Date Created: May 27, 2021
Last Modified: March 20, 2022
"""

import multiprocessing
import queue
import signal
import time
from multiprocessing.managers import ListProxy
from multiprocessing.sharedctypes import Synchronized

from loguru import logger
from PIL import ImageChops, ImageStat
from rife_ncnn_vulkan_python.rife_ncnn_vulkan import Rife

ALGORITHM_CLASSES = {"rife": Rife}


class Interpolator(multiprocessing.Process):
    def __init__(
        self,
        processing_queue: multiprocessing.Queue,
        processed_frames: ListProxy,
        pause: Synchronized,
    ) -> None:
        multiprocessing.Process.__init__(self)
        self.processing_queue = processing_queue
        self.processed_frames = processed_frames
        self.pause = pause

        self.running = False
        self.processor_objects = {}

        signal.signal(signal.SIGTERM, self._stop)

    def run(self) -> None:
        self.running = True
        logger.opt(colors=True).info(
            f"Interpolator process <blue>{self.name}</blue> initiating"
        )
        while self.running is True:
            try:
                # pause if pause flag is set
                if self.pause.value is True:
                    time.sleep(0.1)
                    continue

                try:
                    # get new job from queue
                    (
                        frame_index,
                        (image0, image1),
                        (difference_threshold, algorithm),
                    ) = self.processing_queue.get(False)
                except queue.Empty:
                    time.sleep(0.1)
                    continue

                # if image0 is None, image1 is the first frame
                # skip this round
                if image0 is None:
                    continue

                # calculate the %diff between the current frame and the previous frame
                difference = ImageChops.difference(image0, image1)
                difference_stat = ImageStat.Stat(difference)
                difference_ratio = (
                    sum(difference_stat.mean) / (len(difference_stat.mean) * 255) * 100
                )

                # if the difference is lower than threshold
                # process the interpolation
                if difference_ratio < difference_threshold:

                    # select a processor object with the required settings
                    # create a new object if none are available
                    processor_object = self.processor_objects.get(algorithm)
                    if processor_object is None:
                        processor_object = ALGORITHM_CLASSES[algorithm](0)
                        self.processor_objects[algorithm] = processor_object
                    interpolated_image = processor_object.process(image0, image1)

                # if the difference is greater than threshold
                # there's a change in camera angle, ignore
                else:
                    interpolated_image = image0

                if frame_index == 1:
                    self.processed_frames[0] = image0
                self.processed_frames[frame_index * 2 - 1] = interpolated_image
                self.processed_frames[frame_index * 2] = image1

            # send exceptions into the client connection pipe
            except (SystemExit, KeyboardInterrupt):
                break

            except Exception as error:
                logger.exception(error)
                break

        logger.opt(colors=True).info(
            f"Interpolator process <blue>{self.name}</blue> terminating"
        )
        return super().run()

    def _stop(self, _signal_number, _frame) -> None:
        self.running = False
