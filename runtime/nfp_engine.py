#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Nightmare Fuzzing Project
This is the generator of samples based on the configure project engines.
@author: joxean
"""

import os
import sys
import time
import json
import zlib
import base64
import random
import shutil
import tempfile

from hashlib import sha1
from threading import Lock
from multiprocessing import Process

from nfp_db import webpy_connect_db as connect_db, init_web_db
from nfp_queue import get_queue
from nfp_process import process_manager
from nfp_log import log as nfplog, debug

#-----------------------------------------------------------------------
log_lock = Lock()
def log(msg):
  log_lock.acquire()
  try:
    nfplog(msg)
  finally:
    log_lock.release()

#-----------------------------------------------------------------------
class CSamplesGenerator:
  def __init__(self):
    self.db = init_web_db()
    self.db.printing = False
    self.read_config()
    
    self.queue_lock = Lock()

  def read_config(self):
    log("Reading configuration from database...")
    self.config = {}
    res = self.db.select("config", what="name, value")
    for row in res:
      self.config[row.name] = row.value
      log("Configuration value %s is %s" % (row.name, row.value))

    # Create the corresponding directory if it doesn't exists
    if not os.path.exists(self.config["WORKING_PATH"]):
      os.makedirs(self.config["WORKING_PATH"])

    # In Linux, it's recommended to use /dev/shm for speed improvements
    if not "TEMPORARY_PATH" in self.config:
      if os.path.exists("/dev/shm"):
        try:
          os.mkdir("/dev/shm/nfp")
        except:
          if os.path.exists("/dev/shm/nfp"):
            self.config["TEMPORARY_PATH"]  = "/dev/shm/nfp"
      self.config["TEMPORARY_PATH"] = None
    
    if self.config["TEMPORARY_PATH"] is not None:
      if not os.path.exists(self.config["TEMPORARY_PATH"]):
        os.mkdir(self.config["TEMPORARY_PATH"])

  def get_project_engines(self):
    res = self.db.query(""" select p.name project_name,
                                   subfolder,
                                   tube_prefix,
                                   command,
                                   maximum_samples,
                                   p.project_id project_id,
                                   me.mutation_engine_id mutation_engine_id,
                                   me.name mutation_generator
                              from projects p,
                                   project_engines pe,
                                   mutation_engines me
                             where p.project_id = pe.project_id
                               and me.mutation_engine_id = pe.mutation_engine_id
                               and p.enabled = 1
                               and ifnull((select iteration
                                      from statistics s
                                     where project_id = p.project_id
                                       and mutation_engine_id = -1), 0) < p.maximum_iteration
                             order by rand()""")
    return res

  def read_random_file(self, folder):
    files = os.listdir(folder)
    filename = random.choice(files)
    return os.path.join(folder, filename)

  def get_command(self, cmd, filename, subfolder):
    cmd = cmd.replace("%INPUT%", '"%s"' % filename)
    temp_file = tempfile.mktemp(dir=self.config["TEMPORARY_PATH"])
    cmd = cmd.replace("%OUTPUT%", temp_file)
    cmd = cmd.replace("%FOLDER%", subfolder)
    for key in self.config:
      value = "%" + key + "%"
      cmd = cmd.replace(value, self.config[key])
    return cmd, temp_file

  def create_sample(self, pe):
    template_folder = os.path.join(self.config["WORKING_PATH"], pe.subfolder, "templates")
    tube_prefix = pe.tube_prefix
    command = pe.command
    project_id = pe.project_id
    mutation_engine_id = pe.mutation_engine_id

    filename = self.read_random_file(template_folder)
    template_hash = os.path.basename(filename)
    debug("Random template file %s" % filename)
    cmd, temp_file = self.get_command(command, filename, template_folder)
    log("Generating mutated file %s" % temp_file)
    debug("*** Command: %s" % cmd)
    os.system(cmd)

    self.queue_lock.acquire()
    try:
      log("Putting it in queue and updating statistics...")
      buf = file(temp_file, "rb").read()
      q = get_queue(watch=False, name="%s-samples" % tube_prefix)

      data = {
        'sample': base64.b64encode(zlib.compress(buf)),
        'temp_file': temp_file,
        'template_hash': template_hash
      }

      q.put(json.dumps(data))
      self.update_statistics(project_id, mutation_engine_id)
      self.update_iteration(project_id)
    except:
      log("Error putting job in queue: %s" % str(sys.exc_info()[1]))
      log("Removing temporary file %s" % temp_file)
      try:
        os.remove(temp_file)
      except:
        pass

      if os.path.exists("%s.diff" % temp_file):
        log("Removing temporary diff file %s" % temp_file)
        os.remove("%s.diff" % temp_file)
    finally:
      self.queue_lock.release()

  def update_iteration(self, project_id):
    what = "statistic_id, iteration iter_value"
    vars = {"project_id":project_id}
    where = "project_id = $project_id and mutation_engine_id = -1"
    res = self.db.select("statistics", what=what, where=where, vars=vars)
    res = list(res)
    with self.db.transaction():
      if len(res) == 0:
        print "insert"
        self.db.insert("statistics", project_id=project_id,
                       mutation_engine_id=-1, total=0, iteration=0)
      else:
        row = res[0]
        vars = {"id":row.statistic_id}
        where = "statistic_id = $id"
        iter_value = row.iter_value
        if row.iter_value is None:
          iter_value = 0
        total = self.db.update("statistics", iteration=iter_value+1, where=where, vars=vars)

  def update_statistics(self, project_id, mutation_engine_id):
    sql = "select statistic_id, total, iteration from statistics where project_id = %s and mutation_engine_id = %s"
    what = "statistic_id, total, iteration"
    vars = {"project_id":project_id, "mutation_engine_id":mutation_engine_id}
    where = "project_id = $project_id and mutation_engine_id = $mutation_engine_id"
    res = self.db.select("statistics", what=what, where=where, vars=vars)
    res = list(res)
    with self.db.transaction():
      if len(res) == 0:
        self.db.insert("statistics", project_id=project_id,
                       mutation_engine_id=mutation_engine_id, total=1)
      else:
        row = res[0]
        vars = {"id":row.statistic_id}
        where = "statistic_id = $id"
        total = self.db.update("statistics", total=row.total+1, iteration=row.iteration+1, where=where, vars=vars)

  def queue_is_full(self, tube_name, maximum):
    q = get_queue(watch=True, name=tube_name)
    value = q.stats_tube(tube_name)["current-jobs-ready"]
    debug("Total of %d job(s) in queue" % value)
    return value > maximum-1

  def get_pending_elements(self, tube_name, maximum):
    q = get_queue(watch=True, name=tube_name)
    value = q.stats_tube(tube_name)["current-jobs-ready"]
    debug("Total of %d job(s) in queue" % value)
    return maximum-value

  def remove_obsolete_files(self):
    q = get_queue(watch=True, name="delete")
    while q.stats_tube("delete")["current-jobs-ready"] > 0:
      self.find_crashes()
      job = q.reserve()
      if job.body.find(".") > -1 or job.body.find("/") > -1:
        raise Exception("Invalid filename %s" % job.body)
      sample_file = os.path.join(self.config["TEMPORARY_PATH"], job.body)
      log("Deleting sample file %s" % sample_file)

      try:
        os.remove(sample_file)
        if os.path.exists(sample_file + ".diff"):
          os.remove(sample_file + ".diff")
      except:
        log("Error removing temporary file: %s" % str(sys.exc_info()[1]))
      job.delete()

  def calculate_crash_hash(self, crash_info):
    crash_hash = []
    if "additional" in crash_info:
      if "stack trace" in crash_info["additional"]:
        st = crash_info["additional"]["stack trace"]
        last = max(map(int, st.keys()))

        # First element in the crash hash contains the last 3 nibbles
        # of the $PC.
        tmp = hex(crash_info["pc"])
        crash_hash = [tmp[len(tmp)-3:]]

        # Next elements, will be the last 3 nibbles of each address in
        # the stack trace until, at much, 13 elements.
        for i in range(0, min(last, 13)):
          try:
            tmp = hex(st[str(i)][0])
          except:
            print "calculate_crash_hash: %s: %s" % (str(sys.exc_info()[1]), st)
            tmp = "???"
          crash_hash.append(tmp[len(tmp)-3:])

    return "".join(crash_hash)

  def should_ignore_duplicates(self, project_id):
    what = "1"
    vars = {"project_id":project_id}
    where = "project_id = $project_id and ignore_duplicates = 1"
    res = self.db.select("projects", what=what, where=where, vars=vars)
    res = list(res)
    return len(res) > 0

  def crash_exists(self, project_id, crash_hash):
    what = "1"
    vars = {"project_id":project_id, "crash_hash":crash_hash}
    where = "project_id = $project_id and crash_hash = $crash_hash "
    where += " and crash_hash is not null and crash_hash != ''"
    where += " and length(crash_hash) >= 30"
    res = self.db.select("crashes", what=what, where=where, vars=vars)
    res = list(res)
    return len(res) > 0

  def should_store_crash(self, project_id, crash_hash):
    if self.should_ignore_duplicates(project_id) and \
       self.crash_exists(project_id, crash_hash):
      return False
    return True

  def insert_crash(self, project_id, subfolder, d):
    samples_path = os.path.join(self.config["WORKING_PATH"], subfolder, "samples")
    temp_file = d['temp_file']
    crash_info = d['crash_info']
    template_hash = d['template_hash']
    data = d['data']

    if data is None and not os.path.exists(temp_file):
      log("Test case file %s does not exists!!!!" % temp_file)
      return False
    elif data is not None:
      # There is no file path but, rather, a whole zlib compressed file
      # encoded in base64 so, create a temporary file and write to it
      # the decoded base64 and decompressed zlib stream of data.
      buf = data
      temp_file = tempfile.mktemp(dir=self.config["TEMPORARY_PATH"])

      try:
        with open(temp_file, "wb") as f:
          f.write(zlib.decompress(base64.b64decode(buf)))
      except:
        os.remove(temp_file)
        raise

    with open(temp_file, "rb") as f:
      buf = f.read()

    file_hash = sha1(buf).hexdigest()
    new_path = os.path.join(samples_path, file_hash)
    sample_id = self.db.insert("samples", sample_hash=file_hash, template_hash=template_hash)

    what = "count(*) cnt"
    vars = {"id":project_id}
    where = "project_id=$id"
    res = self.db.select("statistics", what=what, where=where, vars=vars)
    row = res[0]
    total = row.cnt

    crash_hash = self.calculate_crash_hash(crash_info)
    store_crash = self.should_store_crash(project_id, crash_hash)

    if store_crash:
      log("Saving test file %s" % new_path)
      shutil.copy(temp_file, new_path)

      if os.path.exists(temp_file + ".diff"):
        shutil.copy(temp_file + ".diff", new_path + ".diff")

    with self.db.transaction():
      log("Inserting crash $PC 0x%08x Signal %s Exploitability %s Hash %s" %
          (crash_info["pc"], crash_info["signal"], crash_info["exploitable"], crash_hash))
      if crash_info["disasm"] is not None:
        disasm = "%08x %s" % (crash_info["disasm"][0], crash_info["disasm"][1])
      else:
        disasm = "None"

      additional_info = json.dumps(crash_info["additional"])
      if store_crash:
        self.db.insert("crashes", project_id=project_id, sample_id=sample_id,
                       program_counter=crash_info["pc"], crash_signal=crash_info["signal"],
                       exploitability=crash_info["exploitable"],
                       disassembly=disasm, total_samples=total,
                       additional=str(additional_info),
                       crash_hash=crash_hash, status=0)
        log("Crash stored")
      else:
        log("Ignoring and removing already existing crash with hash %s" % crash_hash)
        if os.path.isfile(temp_file):
          os.remove(temp_file)
        if os.path.isfile(temp_file + ".diff"):
          os.remove(temp_file + ".diff")

      self.reset_iteration(project_id)

  def reset_iteration(self, project_id):
    vars = {"project_id":project_id}
    where = "project_id = $project_id and mutation_engine_id = -1"
    self.db.update("statistics", iteration=0, where=where, vars=vars)

  def add_templates(self):
    what = "project_id, name, subfolder"
    res = self.db.select("projects", what=what, where="enabled = 1")

    for row in res:
      project_folder = os.path.join(self.config["WORKING_PATH"], row['subfolder'])
      input_folder = os.path.join(project_folder, "input")

      for i in os.listdir(input_folder):
        i_file = os.path.join(input_folder, i)
        with open(i_file, "rb") as f:
          buf = f.read()
        file_hash = sha1(buf).hexdigest()
        template = os.path.join(project_folder, "templates", file_hash)

        if not os.path.isfile(template):
          log("Adding sample %s to project %s" % (file_hash, row['name']))
          os.rename(i_file, template)
        else:
          os.remove(i_file)

  def find_crashes(self):
    what = "project_id, subfolder, tube_prefix"
    res = self.db.select("projects", what=what, where="enabled = 1")
    
    for row in res:
      tube_name = "%s-crash" % row.tube_prefix
      q = get_queue(watch=True, name=tube_name)
      while q.stats_tube(tube_name)["current-jobs-ready"] > 0:
        job = q.reserve()
        d = json.loads(job.body)
        self.insert_crash(row.project_id, row.subfolder, d)
        job.delete()

  def generate(self):
    log("Starting generator...")
    while 1:
      debug("Add templates...")
      self.add_templates()
      debug("Finding crashes...")
      self.find_crashes()
      debug("Checking files to remove...")
      self.remove_obsolete_files()
      debug("Reading project engines...")
      project_engines = self.get_project_engines()
      created = False

      for pe in project_engines:
        tube_prefix = pe.tube_prefix
        tube_name = "%s-samples" % tube_prefix
        maximum = pe.maximum_samples
        if not self.queue_is_full(tube_name, maximum):
          for i in range(self.get_pending_elements(tube_name, maximum)):
            if self.queue_is_full(tube_name, maximum):
              break

            line = "Creating sample for %s from folder %s for tube %s mutator %s"
            log(line % (pe.project_name, pe.subfolder, pe.tube_prefix, pe.mutation_generator))
            try:
              self.create_sample(pe)
              created = True
            except:
              log("Error creating sample: %s" % str(sys.exc_info()[1]))
              raise
            #break

      if not created:
        time.sleep(0.1)

#-----------------------------------------------------------------------
def do_generate():
  try:
    gen = CSamplesGenerator()
    gen.generate()
  except KeyboardInterrupt:
    log("Aborted")
  except:
    print "Error:", sys.exc_info()[1]
    # Uncomment it for debugging purposes, not for the release
    raise

#-----------------------------------------------------------------------
def main():
  procs = os.getenv("NIGHTMARE_PROCESSES")
  if procs is not None:
    process_manager(int(procs), do_generate, [])
  else:
    do_generate()

if __name__ == "__main__":
  main()
