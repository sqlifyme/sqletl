import multiprocessing
import tempfile
import uuid
import pickle
import os
import json
import time
from .pipeline import Pipeline, TaskGroup
from .datatable import DataTable
from .ctx import Context
from .parser import parse
from .planner import plan


class WorkerMemory:
    def __init__(self, path):
        self.path = path

    def load_pipe_ctx(self, run_id):
        return self.load(f"{run_id}-pipe")
    
    def save_pipe_ctx(self, run_id, pipe, ctx):
        self.save(f"{run_id}-pipe", (pipe, ctx))

    def push_results(self, result_id, data):
        l = self.load(result_id) or []
        l.append(data)
        self.save(result_id, l)

    def load_results(self, result_id):
        return self.load(result_id)

    def load(self, key):
        filename = os.path.join(self.path, key)
        if not os.path.exists(filename):
            return None
        with open(filename, 'rb') as f:
            return pickle.load(f)
        
    def save(self, key, data):
        filename = os.path.join(self.path, key)
        with open(filename, 'wb') as f:
            pickle.dump(data, f)


class Worker:
    def __init__(self, queue, memory: WorkerMemory):
        self.queue = queue
        self.memory = memory

    def run(self):
        while True:
            run_id, task_id, prev_result_id = self.queue.get()
            if run_id is None:
                break
            self.handle_task(run_id, task_id, prev_result_id)
    
    def handle_task(self, run_id, task_id, prev_result_id):
        print(f"Running task {run_id}#{task_id}")
        pipe, ctx = self.memory.load_pipe_ctx(run_id)
        task, task_id, next_task_id = find_task(pipe, task_id)

        deps = self.memory.load_results(prev_result_id) if prev_result_id else None
        if not deps:
            deps = [DataTable()]
        dt = task.run_after_deps(ctx, deps)

        if next_task_id:
            task_path = task_id.split('.')
            next_task_path = next_task_id.split('.')
            if len(next_task_path) > len(task_path):
                result_id = self.task_result_id(run_id, '.'.join(next_task_path[:-2]) + ".in")
                self.memory.push_results(result_id, dt)
            if len(task_path) > 2 and len(task_path) == len(next_task_path) and task_path[-2] != next_task_path[-2]:
                # task from different dependency group
                dep_result_id = self.task_result_id(run_id, '.'.join(task_path[:-2]) + ".out")
                self.memory.push_results(dep_result_id, dt)
                result_id = self.task_result_id(run_id, '.'.join(task_path[:-2]) + ".in") # result for first task of next group in deps is the result of tasks before this groups of deps
            elif len(next_task_path) < len(task_path):
                # going back to parent group
                result_id = self.task_result_id(run_id, '.'.join(task_path[:-2]) + ".out")
                self.memory.push_results(result_id, dt)
            else:
                result_id = self.task_result_id(run_id, task_id)
                self.memory.push_results(result_id, dt)

            self.queue.put((run_id, next_task_id, result_id))
        else:
            self.memory.push_results(run_id, dt)
    
    def task_result_id(self, run_id, task_id):
        return f"{run_id}-{task_id}"
    

def pool_worker(queue, memory):
    print("Worker started")
    worker = Worker(queue, memory)
    worker.run()


class Runner:
    def __init__(self, pool_size=None, cache_path=None):
        self.pool_size = pool_size or multiprocessing.cpu_count()
        self.queue = multiprocessing.Queue()
        self.memory = WorkerMemory(cache_path or tempfile.mkdtemp())

    def start(self):
        self.pool = multiprocessing.Pool(self.pool_size, pool_worker, (self.queue, self.memory))

    def stop(self):
        for _ in range(self.pool_size):
            self.queue.put((None, None, None))
        self.pool.close()
        self.pool.join()

    def execute(self, query: str, ctx: Context = None):
        ast = parse(query)
        pipe = plan(ast)
        if not ctx:
            ctx = Context()
        return self.run(pipe, ctx)

    def run(self, pipe: Pipeline, ctx: Context):
        run_id = str(uuid.uuid4())
        task_id = find_first_task(pipe)
        self.memory.save_pipe_ctx(run_id, pipe, ctx)
        self.queue.put((run_id, task_id, None))
        return run_id
    
    def get(self, run_id):
        res = self.memory.load_results(run_id)
        return res[0] if res else None


class RedisMemory:
    def __init__(self, client):
        self.client = client

    def push_results(self, key, data):
        self.client.rpush(key, pickle.dumps(data))

    def load_results(self, key):
        return [pickle.loads(v) for v in self.client.lrange(key, 0, -1)]

    def load(self, key):
        return pickle.loads(self.client.get(key))
        
    def save(self, key, data):
        self.client.set(key, pickle.dumps(data))


class RedisQueue:
    def __init__(self, client, queue):
        self.client = client
        self.queue = queue
        self.pubsub = client.pubsub()
        self.pubsub.subscribe(queue)

    def get(self):
        while True:
            msg = self.pubsub.get_message()
            if not msg:
                time.sleep(0.001)
                continue
            if msg["type"] != "message":
                continue
            return json.loads(msg["data"].decode())

    def put(self, data):
        self.client.publish(self.queue, json.dumps(data))


def redis_pool_worker(redis_url):
    client = Redis.from_url(redis_url)
    queue = RedisQueue(client, queue)
    memory = RedisMemory(client)
    pool_worker(queue, memory)


class RedisRunner(Runner):
    def __init__(self, redis_url, queue="sqletl", pool_size=None):
        self.pool_size = pool_size or multiprocessing.cpu_count()
        self.redis_url = redis_url
        self.client = Redis.from_url(redis_url)
        self.queue = RedisQueue(self.client, queue)
        self.memory = RedisMemory(self.client)

    def start(self):
        self.pool = multiprocessing.Pool(self.pool_size, redis_pool_worker, (self.redis_url,))


def find_first_task(tasks: TaskGroup, parent_path=None, from_idx=0):
    task = tasks.tasks[from_idx]
    task_id = f"{parent_path}.{from_idx}" if parent_path else str(from_idx)
    if task.dependencies:
        return find_first_task(task.dependencies[0], f"{task_id}.0")
    return task_id


def find_task(tasks: TaskGroup, task_id, parent_path=None):
    idx, deps_path = task_id.split('.', 1) if '.' in task_id else (task_id, None)
    idx = int(idx)
    task = tasks.tasks[idx]
    task_id = f"{parent_path}.{idx}" if parent_path else str(idx)
    next_task_id = None

    if deps_path:
        dep_idx, deps_path = deps_path.split('.', 1) if '.' in deps_path else (deps_path, None)
        dep_idx = int(dep_idx)
        parent_task_id = task_id
        parent_task = task
        task, task_id, next_task_id = find_task(parent_task.dependencies[dep_idx], deps_path, f"{parent_task_id}.{dep_idx}")
        if not next_task_id and dep_idx + 1 < len(parent_task.dependencies):
            # next deps group
            next_task_id = f"{parent_task_id}.{dep_idx + 1}.0"
        elif not next_task_id:
            next_task_id = parent_task_id

    if not next_task_id:
        next_task_idx = idx + 1 if idx + 1 < len(tasks.tasks) else None
        if next_task_idx:
            next_task_id = find_first_task(tasks, parent_path, next_task_idx)

    return task, task_id, next_task_id