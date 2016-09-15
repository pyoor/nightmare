#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Nightmare Fuzzing Project web frontend
Created on Sat May 18 21:35:33 2013
@author: joxean
"""

import os
import sys
import web
import json
import shutil

from hashlib import sha1
from zipfile import ZipFile
from tempfile import mkstemp
from base64 import b64decode
from web import form, background
from web.background import background, backgrounder

from nfp_db import init_web_db, webpy_connect_db as connect_db
from nfp_queue import get_queue
from config import NFP_USER, NFP_PASS
from kfuzzy import CKoretFuzzyHashing
from diff_match_patch import diff_match_patch

from inmemoryzip import InMemoryZip

#-----------------------------------------------------------------------
urls = (
    '/', 'index',
    '/config', 'config',
    '/users', 'users',
    '/projects', 'projects',
    '/engines', 'mutation_engines',
    '/project_engines', 'project_engines',
    '/project_triggers', 'project_triggers',
    '/nodes', 'nodes',
    '/results', 'results',
    '/bugs', 'bugs',
    '/statistics', 'statistics',
    '/login', 'login',
    '/logout', 'logout',
    '/favicon.ico', 'favicon',
    '/add_project', 'add_project',
    '/edit_project', 'edit_project',
    '/del_project', 'del_project',
    '/add_mutation_engine', 'add_mutation_engine',
    '/edit_mutation_engine', 'edit_mutation_engine',
    '/del_mutation_engine', 'del_mutation_engine',
    '/update_project_engine', 'update_project_engine',
    '/view_crash', 'view_crash',
    '/next_crash', 'next_crash',
    '/download_sample', 'download_sample',
    '/find_samples', 'find_samples',
    '/find_original', 'find_original',
    '/show_diff', 'show_diff',
    '/download_project', 'download_project',
    '/triggers', 'triggers'
)

app = web.application(urls, globals())
render = web.template.render('templates/')
if web.config.get('_session') is None:
  session = web.session.Session(app, web.session.DiskStore('sessions'), {'user':None})
  web.config._session = session
else:
  session = web.config._session

register_form = form.Form(
  form.Textbox("username", description="Username"),
  form.Password("password", description="Password"),
  form.Button("submit", type="submit", description="Login"),
  validators = [
    form.Validator("All fields are mandatory", lambda i: i.username == "" or i.password == "")]
)

#-----------------------------------------------------------------------
# FUNCTIONS

#-----------------------------------------------------------------------
def myrepr(buf):
  if buf:
    return repr(buf)
  return

#-----------------------------------------------------------------------
# CLASSES

#-----------------------------------------------------------------------
class favicon: 
  def GET(self): 
    f = open("static/favicon.ico", 'rb')
    return f.read()

#-----------------------------------------------------------------------
class login:
  def POST(self):
    i = web.input(username="", password="")
    if i.username == "" or i.password == "":
      return render.error("Invalid username or password")
    elif i.username != NFP_USER or sha1(i.password).hexdigest() != NFP_PASS:
      return render.error("Invalid username or password")
    session.user = i.username
    return web.seeother("/")

#-----------------------------------------------------------------------
class logout:
  def GET(self):
    session.user = None
    del session.user
    return web.seeother("/")

#-----------------------------------------------------------------------
class nodes:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    return render.nodes()

#-----------------------------------------------------------------------
class index:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    return render.index()

#-----------------------------------------------------------------------
class config:
  def POST(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    
    i = web.input(working_path="", nightmare_path="", temporary_path="")
    if i.working_path == "" or i.nightmare_path == "" or i.temporary_path == "":
      render.error("Invalid samples, templates, temporary or nightmare path")
    
    db = init_web_db()
    with db.transaction():
      sql = "select 1 from config where name = 'WORKING_PATH'"
      res = list(db.query(sql))
      if len(res) > 0:
        sql = "update config set value = $value where name = 'WORKING_PATH'"
      else:
        sql = "insert into config (name, value) values ('WORKING_PATH', $value)"
      db.query(sql, vars={"value":i.working_path})
      
      sql = "select 1 from config where name = 'NIGHTMARE_PATH'"
      res = list(db.query(sql))
      if len(res) > 0:
        sql = "update config set value = $value where name = 'NIGHTMARE_PATH'"
      else:
        sql = "insert into config (name, value) values ('NIGHTMARE_PATH', $value)"
      db.query(sql, vars={"value":i.nightmare_path})
      
      sql = "select 1 from config where name = 'TEMPORARY_PATH'"
      res = list(db.query(sql))
      if len(res) > 0:
        sql = "update config set value = $value where name = 'TEMPORARY_PATH'"
      else:
        sql = "insert into config (name, value) values ('TEMPORARY_PATH', $value)"
      db.query(sql, vars={"value":i.temporary_path})

      sql = "select 1 from config where name = 'QUEUE_HOST'"
      res = list(db.query(sql))
      if len(res) > 0:
        sql = "update config set value = $value where name = 'QUEUE_HOST'"
      else:
        sql = "insert into config (name, value) values ('QUEUE_HOST', $value)"
      db.query(sql, vars={"value":i.queue_host})

      sql = "select 1 from config where name = 'QUEUE_PORT'"
      res = list(db.query(sql))
      if len(res) > 0:
        sql = "update config set value = $value where name = 'QUEUE_PORT'"
      else:
        sql = "insert into config (name, value) values ('QUEUE_PORT', $value)"
      db.query(sql, vars={"value":i.queue_port})

    return web.redirect("/config")

  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    
    db = init_web_db()
    sql = """select name, value
               from config
               where name in ('WORKING_PATH', 'NIGHTMARE_PATH', 'TEMPORARY_PATH', 'QUEUE_HOST', 'QUEUE_PORT')"""
    res = db.query(sql)

    working_path = ""
    nightmare_path = ""
    temporary_path = ""
    queue_host = "localhost"
    queue_port = 11300
    for row in res:
      name, value = row.name, row.value
      if name == 'WORKING_PATH':
        working_path = value
      elif name == 'NIGHTMARE_PATH':
        nightmare_path = value
      elif name == 'TEMPORARY_PATH':
        temporary_path = value
      elif name == 'QUEUE_HOST':
        queue_host = value
      elif name == 'QUEUE_PORT':
        queue_port = value

    return render.config(working_path, nightmare_path, temporary_path, queue_host, queue_port)

#-----------------------------------------------------------------------
class users:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    return render.users()

#-----------------------------------------------------------------------
class projects:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)

    i = web.input(show_all=0)
    db = init_web_db()
    sql = "select * from projects order by date desc"
    res = db.query(sql)
    return render.projects(res, i.show_all)

#-----------------------------------------------------------------------
class add_project:
  def POST(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    
    i = web.input(name="", description="", subfolder="", tube_prefix="",
                  max_files=100, max_iteration=1000000,
                  ignore_duplicates=0)
    if i.name == "":
      return render.error("No project name specified")
    elif i.description == "":
      return render.error("No project description specified")
    elif i.tube_prefix == "":
      return render.error("Invalid tube prefix")
    
    if i.ignore_duplicates == "on":
      ignore_duplicates = 1
    else:
      ignore_duplicates = 0

    db = init_web_db()
    sql = """select value from config where name in ('WORKING_PATH')"""
    res = db.query(sql)
    res = list(res)
    working_path = res[0]['value']

    with db.transaction():
      db.insert("projects", name=i.name, description=i.description,
              subfolder=i.subfolder, tube_prefix=i.tube_prefix, 
              maximum_samples=i.max_files, archived=0,
              maximum_iteration=i.max_iteration,
              date=web.SQLLiteral("CURRENT_DATE"),
              ignore_duplicates=ignore_duplicates)

    project_folder = os.path.join(working_path, i.subfolder)
    if not os.path.exists(project_folder):
      os.makedirs(project_folder)

    if not os.path.exists(os.path.join(project_folder, "samples")):
      os.makedirs(os.path.join(project_folder, "samples"))

    if not os.path.exists(os.path.join(project_folder, "templates")):
      os.makedirs(os.path.join(project_folder, "templates"))

    if not os.path.exists(os.path.join(project_folder, "input")):
      os.makedirs(os.path.join(project_folder, "input"))

    return web.redirect("/projects")

#-----------------------------------------------------------------------
class edit_project:
  def POST(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    i = web.input(id=-1, name="", description="", subfolder="",
                  tube_prefix="", enabled="", archived="",
                  ignore_duplicates=0)
    if i.id == -1:
      return render.error("Invalid project identifier")
    elif i.name == "":
      return render.error("No project name specified")
    elif i.description == "":
      return render.error("No project description specified")
    elif i.tube_prefix == "":
      return render.error("No tube prefix specified")

    if i.enabled == "on":
      enabled = 1
    else:
      enabled = 0
    
    if i.archived == "on":
      archived = 1
    else:
      archived = 0

    if i.ignore_duplicates == "on":
      ignore_duplicates = 1
    else:
      ignore_duplicates = 0

    db = init_web_db()

    sql = """select value from config where name in ('WORKING_PATH')"""
    res = db.query(sql)
    res = list(res)
    working_path = res[0]['value']

    what = """project_id, name, description, subfolder, tube_prefix,
              maximum_samples, enabled, date, archived,
              maximum_iteration, ignore_duplicates """
    where = "project_id = $project_id"
    vars = {"project_id":i.id}
    res = db.select("projects", what=what, where=where, vars=vars)
    res = list(res)

    old_path = os.path.join(working_path, res[0]['subfolder'])
    new_path = os.path.join(working_path, i.subfolder)
    print old_path, new_path
    if os.path.isfile(old_path) and old_path != new_path:
      shutil.move(old_path, new_path)
    elif old_path != new_path:
      os.makedirs(new_path)
      os.makedirs(os.path.join(new_path, "samples"))
      os.makedirs(os.path.join(new_path, "templates"))
      os.makedirs(os.path.join(new_path, "input"))

    if len(res) == 0:
      return render.error("Invalid project identifier")

    with db.transaction():
      enabled = i.enabled == "on"
      archived = i.archived == "on"
      db.update("projects", name=i.name, description=i.description, 
                subfolder=i.subfolder, tube_prefix=i.tube_prefix,
                maximum_samples=i.max_files, enabled=enabled,
                maximum_iteration=i.max_iteration,
                archived=archived, where="project_id = $project_id",
                ignore_duplicates=ignore_duplicates,
                vars={"project_id":i.id})
    return web.redirect("/projects")
  
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    i = web.input(id=-1)
    if i.id == -1:
      return render.error("Invalid project identifier")
    
    db = init_web_db()
    what = """project_id, name, description, subfolder, tube_prefix,
              maximum_samples, enabled, date, archived,
              maximum_iteration, ignore_duplicates """
    where = "project_id = $project_id"
    vars = {"project_id":i.id}
    res = db.select("projects", what=what, where=where, vars=vars)
    res = list(res)
    if len(res) == 0:
      return render.error("Invalid project identifier")
    return render.edit_project(res[0])

#-----------------------------------------------------------------------
class del_project:
  def POST(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    i = web.input(id=-1, sure="")
    if i.id == -1:
      return render.error("Invalid project identifier")
    elif i.sure != "on":
      return render.error("You must check the \"I'm sure\" field.")
    
    db = init_web_db()

    sql = """select value from config where name in ('WORKING_PATH')"""
    res = db.query(sql)
    res = list(res)
    working_path = res[0]['value']

    what = """project_id, name, description, subfolder, tube_prefix,
              maximum_samples, enabled, date, archived,
              maximum_iteration, ignore_duplicates """
    where = "project_id = $project_id"
    vars = {"project_id":i.id}
    res = db.select("projects", what=what, where=where, vars=vars)
    res = list(res)

    shutil.rmtree(os.path.join(working_path, res[0]['subfolder']))

    with db.transaction():
      vars={"project_id":i.id}
      where = "project_id=$project_id"
      db.delete("projects", where=where, vars=vars)
    return web.redirect("/projects")

  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    i = web.input(id=-1)
    if i.id == -1:
      return render.error("Invalid project identifier")
    return render.del_project(i.id)

#-----------------------------------------------------------------------
class triggers:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)

    db = init_web_db()
    sql = "select * from triggers order by date desc"
    res = db.query(sql)
    return render.triggers(res)

#-----------------------------------------------------------------------
class mutation_engines:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    
    db = init_web_db()
    res = db.select("mutation_engines", order="date desc")
    return render.mutation_engines(res)

#-----------------------------------------------------------------------
class add_mutation_engine:
  def POST(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    i = web.input(name="", description="", command="")

    if i.name == "":
      return render.error("No mutation engine name specified")
    elif i.description == "":
      return render.error("No mutation engine description specified")
    elif i.command == "":
      return render.error("No mutation engine command specified")
    elif i.command.find("%OUTPUT%") == -1:
      return render.error("No output mutated filename specified in the mutation engine command")
    
    db = init_web_db()
    with db.transaction():
      db.insert("mutation_engines", name=i.name, command=i.command,
                description=i.description, date=web.SQLLiteral("CURRENT_DATE"))
    return web.redirect("/engines")

#-----------------------------------------------------------------------
class edit_mutation_engine:
  def POST(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    i = web.input(id=-1, name="", description="", command="")
    if i.id == -1:
      return render.error("Invalid mutation engine identifier")
    elif i.name == "":
      return render.error("No mutation engine name specified")
    elif i.description == "":
      return render.error("No mutation engine description specified")
    elif i.command == "":
      return render.error("No mutation engine command specified")
    elif i.command.find("%OUTPUT%") == -1:
      return render.error("No output mutated filename specified in the mutation engine command")
    
    db = init_web_db()
    with db.transaction():
      where = "mutation_engine_id = $id"
      vars = {"id":i.id}
      db.update("mutation_engines", name=i.name, command=i.command,
                description=i.description, where=where, vars=vars)
    return web.redirect("/engines")
  
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    i = web.input(id=-1)
    if i.id == -1:
      return render.error("Invalid project identifier")
    
    db = init_web_db()
    what = "mutation_engine_id, name, description, command, date"
    where = "mutation_engine_id = $id"
    vars = {"id":i.id}
    res = db.select("mutation_engines", what=what, where=where, vars=vars)
    res = list(res)
    if len(res) == 0:
      return render.error("Invalid mutation engine identifier")
    return render.edit_mutation_engine(res[0])

#-----------------------------------------------------------------------
class del_mutation_engine:
  def POST(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    i = web.input(id=-1, sure="")
    if i.id == -1:
      return render.error("Invalid mutation engine identifier")
    elif i.sure != "on":
      return render.error("You must check the \"I'm sure\" field.")
    
    db = init_web_db()
    with db.transaction():
      where = "mutation_engine_id = $id"
      vars = {"id":i.id}
      db.delete("mutation_engines", where=where, vars=vars)
    return web.redirect("/engines")
  
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    i = web.input(id=-1)
    if i.id == -1:
      return render.error("Invalid mutation engine identifier")
    return render.del_mutation_engine(i.id)

#-----------------------------------------------------------------------
class project_engines:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)

    db = init_web_db()
    what="project_id, name"
    where="archived != 1"
    order="enabled desc, project_id desc"
    projects = db.select("projects", what=what, where=where, order=order)

    what = "project_id, mutation_engine_id"
    rows = db.select("project_engines")
    project_engines = {}
    for row in rows:
      try:
        project_engines[row.project_id].append(row.mutation_engine_id)
      except:
        project_engines[row.project_id] = [row.mutation_engine_id]

    what = "mutation_engine_id, name"
    engines = list(db.select("mutation_engines", what=what))

    return render.project_engines(projects, project_engines, engines)

#-----------------------------------------------------------------------
class project_triggers:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    return render.error("Not yet implemented")

#-----------------------------------------------------------------------
class update_project_engine:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    
    i = web.input(engines=[], project_id=None)
    if i.project_id is None:
      return render.error("Invalid project identifier")

    db = init_web_db()
    with db.transaction():
      vars = {"id":i.project_id}
      where = "project_id = $id"
      db.delete("project_engines", where=where, vars=vars)

      # And insert ignoring errors all selected ones
      for engine in i.engines:
        try:
          db.insert("project_engines", project_id=i.project_id, 
                    mutation_engine_id = engine)
        except:
          pass

    web.seeother("/project_engines")

#-----------------------------------------------------------------------
class results:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    
    i = web.input(show_all=0, field="", fieldValue="", no_field="",
                  no_fieldValue="", sortValue="", hideDup="")

    db = init_web_db()
    # XXX: There is neither CONV nor CONCAT functions in either PgSQL or
    # SQLite so, in order to support them, I have to create a function
    # for both SQLite and PgSQL to mimic this behaviour.
    if i.hideDup != "":
      hide_dup=True
      sql = """ SELECT crash_id,
                     p.project_id,
                     p.name,
                     sample_id,
                     Concat('0x?????', Substr(Conv(program_counter, 10, 16),
                                       Length(Conv(program_counter, 10, 16)) - 2)) pc,
                     crash_signal,
                     exploitability,
                     disassembly,
                     c.date
               FROM    crashes AS c,
                       projects AS p,
                       (SELECT
                           Concat('0x?????', Substr(Conv(program_counter, 10, 16),
                                             Length(Conv(program_counter, 10, 16))-2)) pc,
                           Min(crash_id) min_crash
                       FROM crashes
                       GROUP BY pc) AS c2
               WHERE   p.project_id = c.project_id
                       AND p.enabled = 1
                       AND Concat('0x?????', Substr(Conv(program_counter, 10, 16),
                                             Length(Conv(program_counter, 10, 16))-2)) = c2.pc
                       AND c.crash_id = c2.min_crash """
    else:
      hide_dup=False
      sql = """ select crash_id, p.project_id, p.name, sample_id,
                       concat("0x", CONV(program_counter, 10, 16)) pc,
                       crash_signal, exploitability, disassembly, c.date
                  from crashes c,
                       projects p
                 where p.project_id = c.project_id
                   and p.enabled = 1 """

    valid_fields = ["crash_signal", "program_counter", "exploitability", 
                    "disassembly", "date", "crash_hash"]
    if i.field != "" and i.fieldValue != "":
      if i.field not in valid_fields:
        return render.error("Invalid field %s" % i.field)
      
      value = i.fieldValue.replace("'", "").replace("\n", "")
      if i.field != "program_counter":
        sql += " and lower(c.%s) like lower('%s')" % (i.field, value)
      else:
        sql += " and lower(concat(\"0x\", CONV(program_counter, 10, 16))) like lower('%s')" % (value)

    if i.no_field != "" and i.no_fieldValue != "":
      if i.no_field not in valid_fields:
        return render.error("Invalid field %s" % i.no_field)
      
      value = i.no_fieldValue.replace("'", "").replace("\n", "")
      if i.no_field != "program_counter":
        sql += " and lower(c.%s) not like lower('%s')" % (i.no_field, value)
      else:
        sql += " and lower(concat(\"0x\", CONV(program_counter, 10, 16))) not like lower('%s')" % (value)

    if i.sortValue != "":
      if i.no_field not in valid_fields:
        return render.error("Invalid field %s" % i.no_field)
    
      sql += " ORDER BY %s DESC" % (i.sortValue)
    else:
      sql += " ORDER BY date DESC"
      
    res = db.query(sql)
    results = {}
    for row in res:
      project_name = row.name
      try:
        results[project_name].append(row)
      except:
        results[project_name] = [row]

    return render.results(results, i.show_all, i.field, i.fieldValue,
                          i.no_field, i.no_fieldValue, i.sortValue, hide_dup)

#-----------------------------------------------------------------------
class bugs:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    
    db = init_web_db()
    sql = """ select concat('0x???????', substr(conv(program_counter, 10, 16), length(conv(program_counter, 10, 16))-2)) address,
                     crash_signal, substr(disassembly, instr(disassembly, ' ')+1) dis, count(*) count
                from crashes c,
                     projects p
               where p.project_id = c.project_id
                 and crash_signal != 'UNKNOWN'
                 and p.enabled = 1
               group by 1
               order by 4 desc"""
    bugs = list(db.query(sql))
    
    sql = """ select p.name, 
                     concat('0x???????', substr(conv(program_counter, 10, 16), length(conv(program_counter, 10, 16))-2)) address,
                     crash_signal, substr(disassembly, instr(disassembly, ' ')+1) dis, count(*) count
                from crashes c,
                     projects p
               where p.project_id = c.project_id
                 and crash_signal != 'UNKNOWN'
                 and p.enabled = 1
               group by 1, 2
               order by p.project_id desc"""
    tmp = list(db.query(sql))

    project_bugs = {}
    for bug in tmp:
      try:
        project_bugs[bug["name"]].append(bug)
      except KeyError:
        project_bugs[bug["name"]] = [bug]

    return render.bugs(bugs, project_bugs)

#-----------------------------------------------------------------------
def hexor(buf):
  try:
    return hex(buf)
  except:
    return buf

#-----------------------------------------------------------------------
def render_crash(crash_id):
  # XXX: FIXME: Joxean, why do 2 queries instead of one????
  # Get the project_id from the crash_id
  db = init_web_db()
  vars = {"id":crash_id}
  res = db.select("crashes", where="crash_id=$id", vars=vars)
  crash_row = res[0]

  # Get the project name
  where = "project_id=$id"
  vars = {"id":crash_row.project_id}
  res = db.select("projects", what="name", where=where, vars=vars)
  project_name = res[0].name
  
  crash_data = {}
  crash_data["crash_id"] = crash_row.crash_id
  crash_data["project_id"] = crash_row.project_id
  crash_data["sample_id"] = crash_row.sample_id
  crash_data["program_counter"] = crash_row.program_counter
  crash_data["crash_signal"] = crash_row.crash_signal
  crash_data["exploitability"] = crash_row.exploitability
  crash_data["disassembly"] = crash_row.disassembly
  crash_data["date"] = crash_row.date
  crash_data["total_samples"] = crash_row.total_samples
  crash_data["crash_hash"] = crash_row.crash_hash

  additional = json.loads(crash_row.additional)
  crash_data["additional"] = additional

  return render.view_crash(project_name, crash_data, str=str, map=map, \
                           repr=myrepr, b64=b64decode, sorted=sorted, \
                           type=type, hexor=hexor)

#-----------------------------------------------------------------------
class view_crash:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)

    i = web.input()
    if not i.has_key("id"):
      return render.error("No crash identifier given")

    return render_crash(i.id)

#-----------------------------------------------------------------------
class next_crash:
  def GET(self):
    i = web.input()
    if not i.has_key("id"):
      return render.error("No crash identifier given")

    # XXX: FIXME: Joxean, why do 2 queries instead of one????
    # Get the project_id from the crash_id
    crash_id = i.id
    db = init_web_db()
    vars = {"id":crash_id}
    res = db.select("crashes", where="crash_id=$id", vars=vars)
    crash_row = res[0]

    # Get the project name
    where = "crash_id < $id and project_id = $project_id"
    vars = {"project_id":crash_row.project_id, "id":crash_id}
    rows = db.select("crashes", what="crash_id", where=where, vars=vars, order="crash_id desc")
    if len(rows) > 0:
      crash_id = rows[0].crash_id
      return render_crash(crash_id)
    else:
      return render.error("No more crashes for this project")

#-----------------------------------------------------------------------
class download_sample:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)

    i = web.input()
    if not i.has_key("id"):
      return render.error("No crash identifier given")
    if i.has_key("diff"):
      is_diff = True
    else:
      is_diff = False

    db = init_web_db()
    print i.id
    res = db.query("""SELECT t1.sample_hash,
                             t3.subfolder
                      FROM samples t1
                           JOIN crashes t2
                             ON t1.sample_id = t2.sample_id
                           JOIN projects t3
                             ON t3.project_id = t2.project_id
                      WHERE t1.sample_id = %s""", (i.id,))
    res = list(res)
    if len(res) == 0:
      return render.error("Invalid crash identifier")
    row = res[0]
    sample_hash = row.sample_hash
    subfolder = row.subfolder

    res = db.select("config", what="value", where="name='WORKING_PATH'")
    res = list(res)
    if len(res) == 0:
      return render.error("Invalid configuration value for 'WORKING_PATH'")
    working_path = res[0].value

    path = os.path.join(working_path, subfolder, "samples", sample_hash)
    if not os.path.exists(path):
      return render.error("Crash sample does not exist! %s" % path)

    if is_diff:
      if not os.path.exists(path + ".diff"):
        return render.error("No diff file for this sample. It may be because the mutation engine doesn't generate a diff file.")
      else:
        sample_hash += ".diff"
        path += ".diff"

    web.header("Content-type", "application/octet-stream")
    web.header("Content-disposition", "attachment; filename=%s" % sample_hash)
    f = open(path, 'rb')
    return f.read()

#-----------------------------------------------------------------------
class statistics:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    
    # XXX: TODO: IFNULL is not supported in PgSQL
    sql = """ select p.name,
                     sum(total) total_samples,
                     ifnull((
                        select count(*)
                          from samples s,
                               crashes c
                         where c.sample_id = s.sample_id
                           and project_id = p.project_id
                         group by project_id
                     ), 0) crashes,
                     (
                      select iteration
                        from statistics st
                       where st.project_id = p.project_id
                         and st.mutation_engine_id = -1
                     ) iteration
                from statistics s,
                     projects p,
                     mutation_engines m
               where p.project_id = s.project_id
                 and m.mutation_engine_id = s.mutation_engine_id
                 and p.enabled = 1
               group by p.name """
    db = init_web_db()
    project_stats = db.query(sql)

    sql = """ select distinct exploitability, count(*) count
                from crashes c,
                     projects p
               where p.project_id = c.project_id
                 and p.enabled = 1
               group by exploitability """
    exploitables = db.query(sql)

    sql = """ select distinct crash_signal, count(*) count
                from crashes c,
                     projects p
               where p.project_id = c.project_id
                 and p.enabled = 1
               group by crash_signal """
    signals = db.query(sql)

    sql = """select substr(disassembly, instr(disassembly, ' ')+1) dis, count(*) count
               from crashes c,
                    projects p
               where p.project_id = c.project_id
                and p.enabled = 1
              group by 1"""
    disassemblies = db.query(sql)

    # XXX: TODO: Neither concat nor conv are supported in either PgSQL
    # or SQLite so I need to create a function for these databases.
    sql = """ select concat('0x???????', substr(conv(program_counter, 10, 16), length(conv(program_counter, 10, 16))-2)) address,
                     crash_signal, substr(disassembly, instr(disassembly, ' ')+1) dis, count(*) count
                from crashes c,
                     projects p
               where p.project_id = c.project_id
                 and crash_signal != 'UNKNOWN'
                 and p.enabled = 1
               group by 1
               order by 4 desc"""
    bugs = db.query(sql)

    tubes = {}
    q = get_queue(watch=True, name="delete")
    for tube in q.tubes():
      if tube != "default":
        tubes[tube] = q.stats_tube(tube)["current-jobs-ready"]

    return render.statistics(project_stats, exploitables, signals, disassemblies, bugs, tubes)

#-----------------------------------------------------------------------
class find_samples:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)
    
    db = init_web_db()
    res = list(db.select("config", what="value", where="name = 'TEMPLATES_PATH'"))
    res = list(res)
    if len(res) == 0:
      return render.error("Samples path is not yet configured. Please configure it in the configuration section.")
    return render.find_samples(res[0].value)

  def POST(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)

    i = web.input()
    if not i.has_key('samples_dir'):
      return render.error("No samples sub-directory specified.")
    if not i.has_key('magic'):
      return render.error("No magic header specified.")
    if not i.has_key('extension'):
      return render.error("No file extension specified.")
    if not i.has_key('search'):
      search = ""
    else:
      search = i["search"]
    if i["samples_dir"].find(".") > -1 or \
       i["samples_dir"].find("/") > -1 or \
       i["samples_dir"].find("\\") > -1:
      return render.error("Invalid sub-directory")

    db = init_web_db()
    res = db.select("config", what="value", where="name = 'TEMPLATES_PATH'")
    res = list(res)
    if len(res) == 0:
      return render.error("Samples path is not yet configured. Please configure it in the configuration section.")
    whole_dir = os.path.join(res[0].value, i.samples_dir)

    if not os.path.exists(whole_dir):
      os.makedirs(whole_dir)

    from find_samples import CSamplesFinder
    finder = CSamplesFinder()
    finder.find(i.extension, i.magic, whole_dir, search)
    return render.message("Process finished.")

#-----------------------------------------------------------------------
def find_original_file(db, id):
  # ToDo - Currently broken.  Correct this to handle project folder.
  vars = {"id":id}
  where = "sample_id = $id"
  res = db.select("samples", what="sample_hash", where=where, vars=vars)
  res = list(res)
  if len(res) == 0:
    raise Exception("Invalid crash identifier")
  sample_hash = res[0].sample_hash

  res = db.select("config", what="value", where="name='WORKING_PATH'")
  res = list(res)
  if len(res) == 0:
    raise Exception("Invalid configuration value for 'WORKING_PATH'")

  path = os.path.join(res[0].value, "crashes")
  path = os.path.join(path, sample_hash)
  if not os.path.exists(path):
    raise Exception("Crash sample does not exists! %s" % path)

  magic = open(path, "rb").read(3)
  if magic == "PK\x03":
    z = ZipFile(path, "r")
    cmt = z.comment
    z.close()
    if cmt == "NIGHTMARE":
      raise Exception("Cannot find the original sample for ZIP archives created by Nightmare, sorry.")

  res = db.select("config", what="value", where="name = 'TEMPLATES_PATH'")
  res = list(res)
  if len(res) == 0:
    raise Exception("Invalid configuration value for 'TEMPLATES_PATH'")
  templates_path = res[0].value

  sql = """select p.subfolder subfolder
             from projects p,
                  crashes c
            where c.sample_id = $id
              and p.project_id = c.project_id"""
  vars = {"id":id}
  res = db.query(sql, vars=vars)
  res = list(res)
  if len(res) == 0:
    raise Exception("Cannot find the project associated to the crash identifier")

  project_path = os.path.join(templates_path, res[0].subfolder)
  if not os.path.exists(project_path):
    raise Exception("Cannot find path '%s'" % project_path)

  kfh = CKoretFuzzyHashing()
  kfh.bsize = 16
  h1, h2, h3 = kfh.hash_file(path).split(";")

  original_file = None
  for f in os.listdir(project_path):
    filename = os.path.join(project_path, f)
    if not os.path.isfile(filename):
      continue

    tmp1, tmp2, tmp3 = kfh.hash_file(filename).split(";")
    if h1 == tmp1 and h2 == tmp2 and h3 == tmp3:
      original_file = filename
      break
    elif h1 == tmp1 or h2 == tmp2 or h3 == tmp3:
      original_file = filename
      break

  return original_file, path

#-----------------------------------------------------------------------
class find_original:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)

    i = web.input()
    if not i.has_key("id"):
      return render.error("No crash identifier given")
    if i.has_key("diff"):
      is_diff = True
    else:
      is_diff = False

    db = init_web_db()

    try:
      original_file, crash_file = find_original_file(db, i.id)
    except:
      return render.error(sys.exc_info()[1])

    if original_file is not None:
      basename = os.path.basename(original_file)
      web.header("Content-type", "application/octet-stream")
      web.header("Content-disposition", "attachment; filename=%s" % basename)
      f = open(original_file, 'rb')
      return f.read()

    return render.error("Cannot find original sample.")

#-----------------------------------------------------------------------
def hexdump(src, length=16):
  FILTER = ''.join([(len(repr(chr(x))) == 3) and chr(x) or '.' for x in range(256)])
  lines = []
  for c in xrange(0, len(src), length):
    chars = src[c:c+length]
    hex = ' '.join(["%02x" % ord(x) for x in chars])
    printable = ''.join(["%s" % ((ord(x) <= 127 and FILTER[ord(x)]) or '.') for x in chars])
    lines.append("%04x  %-*s  %s\n" % (c, length*3, hex, printable))
  return ''.join(lines)

#-----------------------------------------------------------------------
class show_diff:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)

    i = web.input()
    if not i.has_key("id"):
      return render.error("No crash identifier given")
    if i.has_key("diff"):
      is_diff = True
    else:
      is_diff = False

    db = connect_db()

    original_file, crash_file = find_original_file(db, i.id)
    if original_file is None:
      return render.error("Cannot find original sample.")

    dmp = diff_match_patch()
    buf1 = open(original_file, "rb").read()
    buf2 = open(crash_file, "rb").read()
    differences = dmp.diff_main(buf1, buf2, False, False)

    return render.show_diff(original_file, crash_file, buf1, buf2, \
                             differences, hexdump)

#-----------------------------------------------------------------------
def get_sample_files(db, i, crash_id):
  sql = """ select sample_hash
              from samples s,
                   crashes c
             where c.crash_id = $id
               and s.sample_id = c.sample_id """
  res = db.query(sql, vars={"id":crash_id})
  res = list(res)
  if len(res) == 0:
    return render.error("Invalid crash identifier")
  row = res[0]
  sample_hash = row.sample_hash

  res = db.select("config", what="value", where="name = 'WORKING_PATH'")
  res = list(res)
  if len(res) == 0:
    return render.error("Invalid configuration value for 'WORKING_PATH'")
  
  path = os.path.join(res[0].value, "samples")
  path = os.path.join(path, sample_hash)
  print path
  if not os.path.exists(path):
    return render.error("Crash sample does not exists! %s" % path)

  ret = [path]
  if os.path.exists(path + ".diff"):
    ret.append(path + ".diff")
  return ret

#-----------------------------------------------------------------------
class download_project:
  def GET(self):
    if not 'user' in session or session.user is None:
      f = register_form()
      return render.login(f)

    i = web.input()
    if not i.has_key("id"):
      return render.error("No project identifier given")

    db = init_web_db()
    sql = """ select min(crash_id) crash_id, concat('0x', substr(conv(program_counter, 10, 16), length(conv(program_counter, 10, 16))-2)) address,
                     crash_signal, substr(disassembly, instr(disassembly, ' ')+1) dis, count(*) count
                from crashes c,
                     projects p
               where p.project_id = c.project_id
                 and crash_signal != 'UNKNOWN'
                 and c.project_id = $id
               group by 2
               order by 5 desc """
    res = db.query(sql, vars={"id":i.id})

    imz = InMemoryZip()
    i = 0
    for row in res:
      i += 1
      samples = get_sample_files(db, i, row.crash_id)
      folder = "bug%d" % i
      imz.append("%s/notes.txt" % folder, ", ".join(map(str, row.values())) + "\n")
      for sample in samples:
        try:
          imz.append("%s/%s" % (folder, os.path.split(sample)[1]), open(sample, "rb").read())
          
          if sample.endswith(".diff"):
            with open(sample, "rb") as f:
              line = f.readline().strip("\r").strip("\n")
              pos = line.find(" was ")
              if pos > -1:
                original_file = line[pos+5:]
                imz.append("%s/original" % folder, open(original_file, "rb").read())
        except:
          imz.append("%s/error.txt" % folder, "Error reading file: %s" % str(sys.exc_info()[1]))

    if i == 0:
      return render.error("There are no results for the specified project")

    # This is horrible
    file_handle, filename = mkstemp()
    imz.writetofile(filename)
    buf = open(filename, "rb").read()
    os.remove(filename)
    filename = sha1(buf).hexdigest()
    web.header("Content-type", "application/octet-stream")
    web.header("Content-disposition", "attachment; filename=%s.zip" % filename)
    return buf

if __name__ == "__main__":
  app.run()
