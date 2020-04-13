import time,hashlib
from collections import namedtuple, OrderedDict
from copy import copy
import six
from six.moves import xrange
import logging
from threading import Thread
#from locust.log import console_logger
#from locust import events

STATS_NAME_WIDTH = 90
CachedResponseTimes = namedtuple("CachedResponseTimes", ["response_times", "num_requests"])
CURRENT_RESPONSE_TIME_PERCENTILE_WINDOW = 10

console_logger = logging.getLogger("console_logger")
console_logger.setLevel(logging.DEBUG)
# create console handler
sh = logging.StreamHandler()
sh.setLevel(logging.DEBUG)
# formatter that doesn't include anything but the message
sh.setFormatter(logging.Formatter('%(message)s'))

console_logger.addHandler(sh)
#console_logger.propagate = False

class StatsEntry(object):
    """
    Represents a single stats entry (name and method)
    """
    
    name = None
    """ Name (URL) of this stats entry """
    
    method = None
    """ Method (GET, POST, PUT, etc.) """
    
    num_requests = None
    """ The number of requests made """
    
    num_failures = None
    """ Number of failed request """
    
    total_response_time = None
    """ Total sum of the response times """
    
    min_response_time = None
    """ Minimum response time """
    
    max_response_time = None
    """ Maximum response time """
    
    num_reqs_per_sec = None
    """ A {second => request_count} dict that holds the number of requests made per second """
    
    response_times = None
    """
    A {response_time => count} dict that holds the response time distribution of all
    the requests.
    
    The keys (the response time in ms) are rounded to store 1, 2, ... 9, 10, 20. .. 90, 
    100, 200 .. 900, 1000, 2000 ... 9000, in order to save memory.
    
    This dict is used to calculate the median and percentile response times.
    """
    
    use_response_times_cache = False
    """
    If set to True, the copy of the response_time dict will be stored in response_times_cache 
    every second, and kept for 20 seconds (by default, will be CURRENT_RESPONSE_TIME_PERCENTILE_WINDOW + 10). 
    We can use this dict to calculate the *current*  median response time, as well as other response 
    time percentiles.
    """
    
    response_times_cache = None
    """
    If use_response_times_cache is set to True, this will be a {timestamp => CachedResponseTimes()} 
    OrderedDict that holds a copy of the response_times dict for each of the last 20 seconds.
    """
    
    total_content_length = None
    """ The sum of the content length of all the requests for this entry """
    
    start_time = None
    """ Time of the first request for this entry """
    
    last_request_timestamp = None
    """ Time of the last request for this entry """
    
    def __init__(self, stats, name, method, use_response_times_cache=False):
        self.stats = stats
        self.name = name
        self.method = method
        self.use_response_times_cache = use_response_times_cache
        self.reset()
    
    def reset(self):
        self.start_time = time.time()
        self.num_requests = 0
        self.num_failures = 0
        self.total_response_time = 0
        self.response_times = {}
        self.min_response_time = None
        self.max_response_time = 0
        self.last_request_timestamp = int(time.time())
        self.num_reqs_per_sec = {}
        self.content_length_per_sec = {}
        self.total_content_length = 0
        self.clps_lst = []
        if self.use_response_times_cache:
            self.response_times_cache = OrderedDict()
            self._cache_response_times(int(time.time()))
    
    def log(self, response_time, content_length):
        # get the time
        t = int(time.time())
        
        if self.use_response_times_cache and self.last_request_timestamp and t > self.last_request_timestamp:
            # see if we shall make a copy of the respone_times dict and store in the cache
            self._cache_response_times(t-1)
        
        self.num_requests += 1        
        self._log_time_of_request(t)
        self._log_response_time(response_time)
        self._log_time_of_content(t, content_length)

        # increase total content-length
        self.total_content_length += content_length

    def _log_time_of_request(self, t):
        self.num_reqs_per_sec[t] = self.num_reqs_per_sec.setdefault(t, 0) + 1
        self.last_request_timestamp = t

    def _log_time_of_content(self, t, length):
        #print("loging====>",t,length)
        self.content_length_per_sec[t] = self.content_length_per_sec.setdefault(t, 0) + length
        self.last_request_timestamp = t        
        
    def _log_response_time(self, response_time):

        self.total_response_time += response_time

        if self.min_response_time is None:
            self.min_response_time = response_time

        self.min_response_time = min(self.min_response_time, response_time)
        self.max_response_time = max(self.max_response_time, response_time)

        # to avoid to much data that has to be transfered to the master node when
        # running in distributed mode, we save the response time rounded in a dict
        # so that 147 becomes 150, 3432 becomes 3400 and 58760 becomes 59000
        if response_time < 100:
            rounded_response_time = response_time
        elif response_time < 1000:
            rounded_response_time = int(round(response_time, -1))
        elif response_time < 10000:
            rounded_response_time = int(round(response_time, -2))
        else:
            rounded_response_time = int(round(response_time, -3))

        # increase request count for the rounded key in response time dict
        self.response_times.setdefault(rounded_response_time, 0)
        self.response_times[rounded_response_time] += 1

    def log_error(self, error):
        self.num_failures += 1

    @property
    def fail_ratio(self):
        try:
            return float(self.num_failures) / (self.num_requests + self.num_failures)
        except ZeroDivisionError:
            if self.num_failures > 0:
                return 1.0
            else:
                return 0.0

    @property
    def avg_response_time(self):
        try:
            return float(self.total_response_time) / self.num_requests
        except ZeroDivisionError:
            return 0

    @property
    def median_response_time(self):
        if not self.response_times:
            return 0

        return median_from_dict(self.num_requests, self.response_times)

    @property
    def current_rps(self):
        if self.stats.last_request_timestamp is None:
            return 0
        slice_start_time = max(self.stats.last_request_timestamp - 12, int(self.stats.start_time or 0))

        reqs = [self.num_reqs_per_sec.get(t, 0) for t in range(slice_start_time, self.stats.last_request_timestamp-2)]
        return avg(reqs)

    @property
    def total_rps(self):
        if not self.stats.last_request_timestamp or not self.stats.start_time:
            return 0.0
        #print("total_rps=======>",self.num_requests,max(self.stats.last_request_timestamp - self.stats.start_time, 1))
        return self.num_requests / max(self.stats.last_request_timestamp - self.stats.start_time, 1)
    
    @property
    def current_clps(self):
        '''
        clps = self.clps_lst[-3:]
        a = avg(clps) 
        #print("current clps %s=======>%s" % (clps,a))        
        '''
        now = int(time.time())
        a = self.total_content_length / max(now - self.stats.start_time, 1)
        #print("current clps=======>%s,%s,%s" % (self.total_content_length, now,self.stats.start_time))
        self.clps_lst.append(a)
        return a
        
    
    @property
    def total_clps(self):        
        #1if not self.stats.last_request_timestamp or not self.stats.start_time:
        #   return 0.0        
        #tclps = self.total_content_length / max(self.stats.last_request_timestamp - self.stats.start_time + 1, 1)
        #print("total_clps:%s=======>%f,%d,%d,%f" % (self.name,self.total_content_length, int(self.stats.start_time), self.stats.last_request_timestamp,tclps))
        
        #2tclps = self.total_content_length / max(self.total_response_time/1000.0, 1.0)
        #print("total_clps:%s=======>%f,%d,%f" % (self.name,self.total_content_length, self.total_response_time,tclps))
        #self.clps_lst.append(tclps)        
        
        #3
        tclps = avg(self.clps_lst)
        return tclps
        
    @property
    def avg_content_length(self):
        try:
            return self.total_content_length / self.num_requests
        except ZeroDivisionError:
            return 0
    
    def extend(self, other):
        """
        Extend the data from the current StatsEntry with the stats from another
        StatsEntry instance. 
        """
        self.last_request_timestamp = max(self.last_request_timestamp, other.last_request_timestamp)
        self.start_time = min(self.start_time, other.start_time)

        self.num_requests = self.num_requests + other.num_requests
        self.num_failures = self.num_failures + other.num_failures
        self.total_response_time = self.total_response_time + other.total_response_time
        self.max_response_time = max(self.max_response_time, other.max_response_time)
        self.min_response_time = min(self.min_response_time or 0, other.min_response_time or 0) or other.min_response_time
        self.total_content_length = self.total_content_length + other.total_content_length

        for key in other.response_times:
            self.response_times[key] = self.response_times.get(key, 0) + other.response_times[key]
        for key in other.num_reqs_per_sec:
            self.num_reqs_per_sec[key] = self.num_reqs_per_sec.get(key, 0) +  other.num_reqs_per_sec[key]
    
    def serialize(self):
        return {
            "name": self.name,
            "method": self.method,
            "last_request_timestamp": self.last_request_timestamp,
            "start_time": self.start_time,
            "num_requests": self.num_requests,
            "num_failures": self.num_failures,
            "total_response_time": self.total_response_time,
            "max_response_time": self.max_response_time,
            "min_response_time": self.min_response_time,
            "total_content_length": self.total_content_length,
            "response_times": self.response_times,
            "num_reqs_per_sec": self.num_reqs_per_sec,
        }
    
    @classmethod
    def unserialize(cls, data):
        obj = cls(None, data["name"], data["method"])
        for key in [
            "last_request_timestamp",
            "start_time",
            "num_requests",
            "num_failures",
            "total_response_time",
            "max_response_time",
            "min_response_time",
            "total_content_length",
            "response_times",
            "num_reqs_per_sec",
        ]:
            setattr(obj, key, data[key])
        return obj
    
    def get_stripped_report(self):
        """
        Return the serialized version of this StatsEntry, and then clear the current stats.
        """
        report = self.serialize()
        self.reset()
        return report

    def __str__(self):
        try:
            fail_percent = (self.num_failures/float(self.num_requests + self.num_failures))*100
        except ZeroDivisionError:
            fail_percent = 0
        
        return (" %-" + str(STATS_NAME_WIDTH) + "s %7d %12s %7.2f %7.2f %7.2f  | %7.2f %7.2f %9.2f %9.2f") % (
            (self.method and self.method + " " or "") + self.name,
            self.num_requests,
            "%d(%.2f%%)" % (self.num_failures, fail_percent),
            self.avg_response_time,
            self.min_response_time or 0,
            self.max_response_time,
            self.median_response_time or 0,
            self.current_rps or 0,
            self.current_clps or 0,
            self.total_content_length or 0
        )
    
    def get_response_time_percentile(self, percent):
        """
        Get the response time that a certain number of percent of the requests
        finished within.
        
        Percent specified in range: 0.0 - 1.0
        """
        return calculate_response_time_percentile(self.response_times, self.num_requests, percent)
    
    def get_current_response_time_percentile(self, percent):
        """
        Calculate the *current* response time for a certain percentile. We use a sliding 
        window of (approximately) the last 10 seconds (specified by CURRENT_RESPONSE_TIME_PERCENTILE_WINDOW) 
        when calculating this.
        """
        if not self.use_response_times_cache:
            raise ValueError("StatsEntry.use_response_times_cache must be set to True if we should be able to calculate the _current_ response time percentile")
        # First, we want to determine which of the cached response_times dicts we should 
        # use to get response_times for approximately 10 seconds ago. 
        t = int(time.time())
        # Since we can't be sure that the cache contains an entry for every second. 
        # We'll construct a list of timestamps which we consider acceptable keys to be used 
        # when trying to fetch the cached response_times. We construct this list in such a way 
        # that it's ordered by preference by starting to add t-10, then t-11, t-9, t-12, t-8, 
        # and so on
        acceptable_timestamps = []
        for i in xrange(9):
            acceptable_timestamps.append(t-CURRENT_RESPONSE_TIME_PERCENTILE_WINDOW-i)
            acceptable_timestamps.append(t-CURRENT_RESPONSE_TIME_PERCENTILE_WINDOW+i)
        
        cached = None
        for ts in acceptable_timestamps:
            if ts in self.response_times_cache:
                cached = self.response_times_cache[ts]
                break
        
        if cached:
            # If we fond an acceptable cached response times, we'll calculate a new response 
            # times dict of the last 10 seconds (approximately) by diffing it with the current 
            # total response times. Then we'll use that to calculate a response time percentile 
            # for that timeframe
            return calculate_response_time_percentile(
                diff_response_time_dicts(self.response_times, cached.response_times), 
                self.num_requests - cached.num_requests, 
                percent,
            )
    
    def percentile(self, tpl=" %-" + str(STATS_NAME_WIDTH) + "s %8d %6d %6d %6d %6d %6d %6d %6d %6d %6d"):
        if not self.num_requests:
            raise ValueError("Can't calculate percentile on url with no successful requests")
        
        return tpl % (
            (self.method and self.method + " " or "") + self.name,
            self.num_requests,
            self.get_response_time_percentile(0.5),
            self.get_response_time_percentile(0.66),
            self.get_response_time_percentile(0.75),
            self.get_response_time_percentile(0.80),
            self.get_response_time_percentile(0.90),
            self.get_response_time_percentile(0.95),
            self.get_response_time_percentile(0.98),
            self.get_response_time_percentile(0.99),
            self.get_response_time_percentile(1.00)
        )
    
    def _cache_response_times(self, t):
        self.response_times_cache[t] = CachedResponseTimes(
            response_times=copy(self.response_times),
            num_requests=self.num_requests,
        )
        
        
        # We'll use a cache size of CURRENT_RESPONSE_TIME_PERCENTILE_WINDOW + 10 since - in the extreme case -
        # we might still use response times (from the cache) for t-CURRENT_RESPONSE_TIME_PERCENTILE_WINDOW-10 
        # to calculate the current response time percentile, if we're missing cached values for the subsequent 
        # 20 seconds
        cache_size = CURRENT_RESPONSE_TIME_PERCENTILE_WINDOW + 10
        
        if len(self.response_times_cache) > cache_size:
            # only keep the latest 20 response_times dicts
            for i in xrange(len(self.response_times_cache) - cache_size):
                self.response_times_cache.popitem(last=False)
class StatsError(object):
    def __init__(self, method, name, error, occurences=0):
        self.method = method
        self.name = name
        self.error = error
        self.occurences = occurences

    @classmethod
    def parse_error(cls, error):
        string_error = repr(error)
        target = "object at 0x"
        target_index = string_error.find(target)
        if target_index < 0:
            return string_error
        start = target_index + len(target) - 2
        end = string_error.find(">", start)
        if end < 0:
            return string_error
        hex_address = string_error[start:end]
        return string_error.replace(hex_address, "0x....")

    @classmethod
    def create_key(cls, method, name, error):
        key = "%s.%s.%r" % (method, name, StatsError.parse_error(error))
        return hashlib.md5(key.encode('utf-8')).hexdigest()

    def occured(self):
        self.occurences += 1

    def to_name(self):
        return "%s %s: %r" % (self.method, 
            self.name, repr(self.error))

    def to_dict(self):
        return {
            "method": self.method,
            "name": self.name,
            "error": StatsError.parse_error(self.error),
            "occurences": self.occurences
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            data["method"], 
            data["name"], 
            data["error"], 
            data["occurences"]
        )

        
class RequestStats(object):
    def __init__(self):
        self.entries = {}
        self.errors = {}
        self.total = StatsEntry(self, "Total", None, use_response_times_cache=True)
        self.start_time = None
    
    @property
    def num_requests(self):
        return self.total.num_requests
    
    @property
    def num_failures(self):
        return self.total.num_failures
    
    @property
    def last_request_timestamp(self):
        return self.total.last_request_timestamp
    
    def log_request(self, method, name, response_time, content_length):
        self.total.log(response_time, content_length)
        self.get(name, method).log(response_time, content_length)
    
    def log_error(self, method, name, error):
        self.total.log_error(error)
        self.get(name, method).log_error(error)
        
        # store error in errors dict
        key = StatsError.create_key(method, name, error)
        entry = self.errors.get(key)
        if not entry:
            entry = StatsError(method, name, error)
            self.errors[key] = entry
        entry.occured()
    
    def get(self, name, method):
        """
        Retrieve a StatsEntry instance by name and method
        """
        entry = self.entries.get((name, method))
        if not entry:
            entry = StatsEntry(self, name, method)
            self.entries[(name, method)] = entry
        return entry
    
    def reset_all(self):
        """
        Go through all stats entries and reset them to zero
        """
        self.start_time = time.time()
        self.total.reset()
        for r in six.itervalues(self.entries):
            r.reset()
    
    def clear_all(self):
        """
        Remove all stats entries and errors
        """
        self.total = StatsEntry(self, "Total", None, use_response_times_cache=True)
        self.entries = {}
        self.errors = {}
        self.start_time = None
    
    def serialize_stats(self):
        return [self.entries[key].get_stripped_report() for key in six.iterkeys(self.entries) if not (self.entries[key].num_requests == 0 and self.entries[key].num_failures == 0)]
    
    def serialize_errors(self):
        return dict([(k, e.to_dict()) for k, e in six.iteritems(self.errors)])



def print_stats(stats):
    console_logger.info((" %-" + str(STATS_NAME_WIDTH) + "s %7s %12s %7s %7s %7s  | %7s %7s %10s %10s") % ('Name', '# reqs', '# fails', 'Avg', 'Min', 'Max', 'Median', 'req/s','Length/s','Total Len'))
    console_logger.info("-" * (80 + STATS_NAME_WIDTH))
    
    total_rps = {}
    total_reqs = {}
    total_failures = {}
    total_clps = {}
    for key in sorted(six.iterkeys(stats)):
        total_rps[key] = 0
        total_reqs[key] = 0
        total_failures[key] = 0
        total_clps[key] = 0
        
    for key in sorted(six.iterkeys(stats)):
        #print("key=====>",key)
        r = stats[key]
        total_rps[key] += r.current_rps  #->total_rps
        total_reqs[key] += r.num_requests
        total_failures[key] += r.num_failures
        total_clps[key] = r.total_clps
        console_logger.info(r)
    console_logger.info("-" * (80 + STATS_NAME_WIDTH))

def calculate_response_time_percentile(response_times, num_requests, percent):
    """
    Get the response time that a certain number of percent of the requests
    finished within. Arguments:
    
    response_times: A StatsEntry.response_times dict
    num_requests: Number of request made (could be derived from response_times, 
                  but we save some CPU cycles by using the value which we already store)
    percent: The percentile we want to calculate. Specified in range: 0.0 - 1.0
    """
    num_of_request = int((num_requests * percent))

    processed_count = 0
    for response_time in sorted(six.iterkeys(response_times), reverse=True):
        processed_count += response_times[response_time]
        if(num_requests - processed_count <= num_of_request):
            return response_time
    

def avg(values):
    return sum(values, 0.0) / max(len(values), 1)

def median_from_dict(total, count):
    """
    total is the number of requests made
    count is a dict {response_time: count}
    """
    pos = (total - 1) / 2
    for k in sorted(six.iterkeys(count)):
        if pos < count[k]:
            return k
        pos -= count[k]

def teardown():
    '''
    console_logger.info("********===========*********============>\n")
    print_stats(global_stats.entries)
    console_logger.info("********===========*********============>\n")
    '''
    global g_running,g_thread
    g_running = False
    stats=global_stats.entries
    console_logger.info("Percentage of the requests completed within given times")
    console_logger.info((" %-" + str(STATS_NAME_WIDTH) + "s %8s %6s %6s %6s %6s %6s %6s %6s %6s %6s") % ('Name', '# reqs', '50%', '66%', '75%', '80%', '90%', '95%', '98%', '99%', '100%'))
    console_logger.info("-" * (80 + STATS_NAME_WIDTH))
    for key in sorted(six.iterkeys(stats)):
        r = stats[key]
        if r.response_times:
            console_logger.info(r.percentile())
    console_logger.info("-" * (80 + STATS_NAME_WIDTH))
    
    total_stats = global_stats.total
    if total_stats.response_times:
        console_logger.info(total_stats.percentile())
    console_logger.info("")
    g_thread.join()
    
def setup():
    global g_thread
    g_thread = Thread(target = stats_printer)
    g_thread.start()   
    pass
    
def stats_printer(): 
    global_stats.reset_all()
    while g_running:
        #print('---------->stats -------------->')
        print_stats(global_stats.entries)
        time.sleep(5)  
    print('stats_printer exiting...')
    
def log_succ(request_type,name,response_time,data_length):
    global_stats.log_request(request_type, name, response_time, data_length)
    

g_running = True
g_thread = None
global_stats = RequestStats()   