import Queue
import collections
import threading
import time


class ApiThreadPool():
    def __init__(self, module):
        self.input = collections.deque()
        self.retry = Queue.Queue()
        self.output = Queue.Queue(100)
        self.logs = Queue.Queue()
        self.module = module
        self.threads = []
        self.pool_lock = threading.Lock()
        self.threadcount = 0
        self.jobcount = 0
        self.jobsadded = False

    def getLogMessage(self):
        try:
            if self.logs.empty():
                msg = None
            else:
                msg = self.logs.get(True, 1)
                self.logs.task_done()
        except Queue.Empty as e:
            msg = None
        finally:
            return msg

    def addRetry(self,job):
        self.retry.put(job)

    def clearRetry(self):
        with self.retry.mutex:
            self.retry.queue.clear()

    def addJob(self, job):
        if job is not None:
            job['number'] = self.jobcount
            self.jobcount += 1
        self.input.append(job)

        if self.jobcount % 10 == 0:
            self.resumeJobs()

    def clearJobs(self):
        self.input.clear()

    def getJob(self):
        try:
            job = self.output.get(True, 1)
            self.output.task_done()
        except Queue.Empty as e:
            job = {'waiting': True}
        finally:
            return job

    def applyJobs(self):
        self.jobsadded = True
        self.resumeJobs()
        # with self.pool_lock:
        #     for x in range(0,self.threadcount):
        #         pass
                #self.addJob(None)  # sentinel empty job

    def hasJobs(self):
        if not self.jobsadded:
            return True

        for thread in self.threads:
            if thread.process.isSet():
                return True

        if len(self.input) > 0:
            return True

        if not self.output.empty():
            return True

        return False

    def addThread(self):
        #self.addJob(None)  # sentinel empty job
        thread = ApiThread(self.input, self.retry, self.output, self.module, self,self.logs)
        self.threadcount += 1
        self.threads.append(thread)

        thread.start()
        thread.process.set()


    def removeThread(self):
        if count(self.threads):
            self.threads[0].halt.set()
            self.threads[0].process.set()

    def processJobs(self,threadcount=None):
        with self.pool_lock:
            if threadcount is not None:
                maxthreads = threadcount
            elif len(self.input) > 50:
                maxthreads = 5
            elif len(self.input) > 10:
                maxthreads = 2
            else:
                maxthreads = 1

            self.threads = []
            for x in range(maxthreads):
                self.addThread()

    def stopJobs(self):
        for thread in self.threads:
            thread.halt.set()
            thread.process.set()

        self.module.disconnectSocket()

    def suspendJobs(self):
        for thread in self.threads:
            thread.process.clear()

    def resumeJobs(self):
        for thread in self.threads:
            thread.process.set()

    def retryJobs(self):
        while not self.retry.empty():
            self.input.appendleft(self.retry.get())
        self.resumeJobs()

    def threadFinished(self):
        with self.pool_lock:
            self.threadcount -= 1
            if (self.threadcount == 0):
                self.clearJobs()
                self.output.put(None)  #sentinel

    def getJobCount(self):
        return len(self.input)

    def getThreadCount(self):
        with self.pool_lock:
            return self.threadcount

    def setThreadCount(self,threadcount):
        with self.pool_lock:
            diff = threadcount - self.threadcount
            if diff > 0:
                for x in range(diff):
                    self.addThread()
            elif diff < 0:
                for x in range(diff):
                    self.removeThread()


class ApiThread(threading.Thread):
    def __init__(self, input, retry, output, module, pool, logs):
        threading.Thread.__init__(self)
        #self.daemon = True
        self.pool = pool
        self.input = input
        self.retry = retry
        self.output = output
        self.module = module
        self.logs = logs
        self.halt = threading.Event()
        self.retry = threading.Event()
        self.process = threading.Event()

    def run(self):
        def streamingData(data, options, headers, streamingTab=False):
            out = {'nodeindex': job['nodeindex'], 'nodedata' : job['nodedata'], 'data': data, 'options': options, 'headers': headers}
            if streamingTab:
                out["streamprogress"] = True
            self.output.put(out)

        def logMessage(msg):
            self.logs.put(msg)

        def logProgress(current=0, total=0):
            self.output.put({'progress': job.get('number', 0),'current':current,'total':total})
            if self.halt.set():
                raise CancelledError('Request cancelled.')
            
        try:
            while not self.halt.isSet():
                try:
                    time.sleep(0)

                    # Get from input queue
                    try:
                        job = self.input.popleft()
                    except:
                        self.process.clear()
                        job = None

                    # Process job
                    if job is not None:
                        self.module.fetchData(job['nodedata'], job['options'], streamingData,logMessage,logProgress)

                    if job is not None:
                        self.output.put({'progress': job.get('number', 0)})
                except Exception as e:
                    logMessage(e)

                self.process.wait()
        finally:
            self.pool.threadFinished()