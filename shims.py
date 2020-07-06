import logging
import time
import yaml
import sys
from typing import Callable, List

import requests


def exp_backoff(f: Callable, tries: int, *args, **kwargs):
    for i in range(tries):
        try:
            f(*args, **kwargs)
        except Exception as e:
            logging.warning(e)
            time.sleep(i**2)
        else:
            break


class LoggingContext:
    def __init__(self, logger: logging.Logger = None, level: int = None,
                 handler: logging.Handler = None, close: bool = True):
        self.logger = logger
        self.handler = handler
        self.close = close
        self.level = level

        if self.logger is None:
            self.logger = logging.root

    def __enter__(self):
        if self.level is not None:
            self.old_level = self.logger.level
            self.logger.setLevel(self.level)
        if self.handler:
            self.logger.addHandler(self.handler)

    def __exit__(self, et, ev, tb):
        if self.level is not None:
            self.logger.setLevel(self.old_level)
        if self.handler:
            self.logger.removeHandler(self.handler)
        if self.handler and self.close:
            self.handler.close()
        # implicit return of None => don't swallow exceptions


class DumbSwitchShim:
    def __init__(self, api: str, trigger_light_ids: List[int], target_light_ids: List[int]):
        self.trigger_light_ids = trigger_light_ids
        self.target_light_ids = target_light_ids
        self.api = api

        self.on = self.lights_reachable()

    def _get_light_reachable(self, light_id: int):
        r = requests.get(f'{self.api}/lights/{light_id}')
        r.raise_for_status()
        return r.json().get("state", {"reachable"}).get("reachable")

    def lights_reachable(self):
        for light in self.trigger_light_ids:
            try:
                if self._get_light_reachable(light):
                    return True
            except Exception as e:
                logging.warning(f"unable to get light status: {e}")
                break
        return False

    def toggle_light(self, light_id: int, on: bool, *_, ttl=3, **__):
        logging.info(f'turning {"on" if on else "off"} {light_id}')
        r = requests.put(f'{self.api}/lights/{light_id}/state', json={"on": on})
        r.raise_for_status()
        # Double check that the light has actually turned on. There seems to be a bug
        # where lights may not turn off. Possibly a connection error when a zigbee link is
        # broken.
        time.sleep(30)
        r = requests.get(f'{self.api}/lights/{light_id}', json={"on": on})
        r.raise_for_status()
        assert r.json().get('state', {}).get('on') == on, \
            "light state doesn't match expected"
        self.on = on

    def run(self):
        logging.info(f'started switch shim (position {"on" if self.on else "off"})')
        while True:
            if self.on:
                # Lights take a while to go offline
                time.sleep(30)
            else:
                # Lights should come on relatively quickly
                time.sleep(5)
            any_reachable = self.lights_reachable()
            if any_reachable:
                if not self.on:
                    with LoggingContext(level=logging.DEBUG):
                        logging.info(f'switch turned on')
                        for light in self.target_light_ids:
                            exp_backoff(self.toggle_light, 3, light, True)
                else:
                    logging.debug(f'switch still on')
            else:
                if self.on:
                    with LoggingContext(level=logging.DEBUG):
                        logging.info(f'switch turned off')
                        for light in self.target_light_ids:
                            exp_backoff(self.toggle_light, 3, light, False)
                else:
                    logging.debug(f'switch still off')


def _run_shims(host: str, uid: str, trigger_light_ids: List[int] = None,
               target_light_ids: List[int] = None, **_):
    api = f'http://{host}/api/{uid}'

    logging.basicConfig(level=logging.INFO)
    switch_shim = DumbSwitchShim(api, trigger_light_ids, target_light_ids)
    switch_shim.run()


if __name__ == "__main__":
    with open(sys.argv[1]) as config_fp:
        config = yaml.safe_load(config_fp)

    for switch_name, switch_conf in config.get("dumbSwitches", {}).items():
        _run_shims(config["host"], config["uid"], **switch_conf)
