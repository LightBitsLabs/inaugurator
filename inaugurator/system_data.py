import logging
from osmosis import sh
import jsonpath_rw_ext
import json
import re


class SystemData:
    def __init__(self):
        self._collected_data = {}

    def get_data(self):
        logging.info("Starting System info collection")
        try:
            output = sh.run(["lshw", "-json"])
            full_lshw_dict = json.loads(output)
            self._parse_system_id(full_lshw_dict)
            self._parse_memory_size()
            self._add_class("processor", full_lshw_dict)
            self._add_class("storage", full_lshw_dict)
            self._add_class("network", full_lshw_dict)
            logging.info("Collected system info dict:%(info)s", dict(info=self._collected_data))
            return dict(self._collected_data)
        except:
            logging.exception("Unable to extract machine info")
            raise

    def clear_data(self):
        self._collected_data = {}

    def _parse_system_id(self, full_lshw_dict):
        result = jsonpath_rw_ext.parse('$.id').find(full_lshw_dict)
        if isinstance(result, list) and result:
            logging.info("System ID: %(id)s", dict(id=result[0].value))
            self._collected_data['id'] = result[0].value
        else:
            logging.exception("Was not able to collect system id")
            raise Exception("Data Collect Error")

    def _parse_memory_size(self):
        output = sh.run(["cat", "/proc/meminfo"])
        for line in output.split('\n'):
            line = line.strip()
            shrink_line = re.sub(' +', ' ', line)
            line_elements = shrink_line.split(" ")
            if line_elements and line_elements[0] == 'MemTotal:':
                mem_size = int(line_elements[1])
                self._collected_data['memory_size'] = mem_size
                logging.info("Mem Avail: %(mem_size)d", dict(mem_size=mem_size))
                break

    def _add_class(self, class_name, full_lshw_dict):
        parse_string = '$..children[?class=' + class_name + ']'
        result = jsonpath_rw_ext.parse(parse_string).find(full_lshw_dict)
        result_data_list = []
        if isinstance(result, list) and result:
            for res in result:
                result_data_list.append(res.value)
            if result_data_list:
                self._collected_data[class_name] = result_data_list
        else:
            logging.exception("Un able to collect data on topic %(topic)s", dict(topic=class_name))
            raise Exception("Data Collect Error")
