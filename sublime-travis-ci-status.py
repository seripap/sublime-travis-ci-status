import sublime
import sublime_plugin
import subprocess
import os
import sys
import json
import webbrowser
import urllib
from threading import Timer

STATUS_BAR_KEY = '(.0.travis-ci-status'

SYMBOLS = {
  'passed': u'passed ✔︎',
  'created': u'created',
  'starting': u'starting...',
  'started': u'in progress...',
  'failed': u'failed ✘',
  'queued': u'queued ◽️',
  'errored': u'errored ⚠',
  'canceled': u'canceled ⃠'
}

# Originally by @pichillilorenzo
# https://github.com/pichillilorenzo/JavaScript-Completions/blob/master/node/repeated_timer.py
class RepeatedTimer(object):
  def __init__(self, interval, function, *args, **kwargs):
    self._timer     = None
    self.interval   = interval
    self.function   = function
    self.args       = args
    self.kwargs     = kwargs
    self.is_running = False
    self.start()

  def _run(self):
    self.is_running = False
    self.start()
    self.function(*self.args, **self.kwargs)

  def start(self):
    if not self.is_running:
      self._timer = Timer(self.interval, self._run)
      self._timer.start()
      self.is_running = True

  def stop(self):
    self._timer.cancel()
    self.is_running = False

# Originally by @pichillilorenzo
# https://github.com/pichillilorenzo/JavaScript-Completions/blob/master/node/animation_loader.py
class AnimationLoader(object):
  def __init__(self, animation, sec, str_before="", str_after="", view=None):
    self.animation = animation
    self.sec = sec
    self.animation_length = len(animation)
    self.str_before = str_before
    self.str_after = str_after
    self.cur_anim = 0
    self.view = view
  def animate(self):
    self.cur_anim = self.cur_anim + 1
    self.view.set_status(STATUS_BAR_KEY, self.str_before+self.animation[self.cur_anim % self.animation_length]+self.str_after)
  def on_complete(self):
    self.view.erase_status(STATUS_BAR_KEY)

class Animation(object):
  def __init__(self, view):
    self.view = view
    self.animation_loader = None
    self.interval_animation = None
  def setLabel(self, label):
    if self.animation_loader is None:
      self.animation_loader = AnimationLoader(["[ • ]", "[ •• ]", "[ ••• ]", "[ •••• ]", "[ ••• ]", "[ •• ]", "[ • ]"], 0.5, label, " ", self.view)
  def start(self):
    if self.animation_loader:
      if self.interval_animation is None:
        self.interval_animation = RepeatedTimer(self.animation_loader.sec, self.animation_loader.animate)
  def is_running(self):
    if self.interval_animation is not None:
      return True
    return False 
  def on_error(self, err):
    self.animation_loader.on_complete()
    self.interval_animation.stop()
  def on_complete(self):
    if self.interval_animation is not None:
      self.animation_loader.on_complete()
      self.interval_animation.stop()
      self.interval_animation = None

class TravisCIStatus(sublime_plugin.EventListener):
  def __init__(self):
    self.settings = sublime.load_settings('Preferences.sublime-settings')
    self.build_started_animation = None

  def get_setting(self, name, view, default = None):
    setting_value = view.settings().get(name, default)

    if setting_value == None:
      setting_value = self.settings.get(name)

    return setting_value

  def on_load(self, view):
    self.run(view)

  def on_new_async(self, view):
    self.run(view)

  def on_clone_async(self, view):
    self.run(view)

  def on_load_async(self, view):
    self.run(view)

  def on_close(self, view):
    self.run(view)

  def on_post_save_async(self, view):
    self.run(view)

  def on_activated_async(self, view):
    self.run(view)

  def run(self, view):
    if view.is_scratch() or view.settings().get('is_widget'):
      return
    
    if self.build_started_animation is None:
      self.build_started_animation = Animation(view)

    self.window = sublime.active_window()

    if self.get_setting('travis_private_projects', view):
      self.TRAVIS_URL = 'https://api.travis-ci.com/'
    else:
      self.TRAVIS_URL = 'https://api.travis-ci.org/'

    self.TOKEN = self.get_setting('travis_api_token', view)

    if self.TOKEN == None or self.TOKEN == '':
      status = 'Missing Travis CI API Token'
    else:
      status = self.get_status()

    # Update the status bar
    if status is not None:
      view.set_status(STATUS_BAR_KEY, status)
    else:
      view.erase_status(STATUS_BAR_KEY)

  def get_status(self):
    repo_info = self.get_repo()
    if repo_info['error'] is not None:
      return repo_info['error']

    build_status = self.make_travis_request(repo_info)
    
    if build_status['build_number'] is not None:
      self.build_started_animation.setLabel( repo_info['branch'] + ' #' + build_status['build_number'] + ' building' )

    status = self.format_status_message(build_status, repo_info)

    if status is not None:
      return status

    return ''

  def format_status_message(self, build_status, repo_info):
    status = None

    if build_status['status'] is not None and repo_info['branch'] is not None:
      if build_status['status'] == 'started':
        if self.build_started_animation.is_running() == False:
          return self.build_started_animation.start()
      else:
        if self.build_started_animation.is_running() == True:
          self.build_started_animation.on_complete()
        status = repo_info['branch'] + ' #' + build_status['build_number'] + ' ' + SYMBOLS[build_status['status']]

    return status

  # Originally by @Section214
  # https://github.com/Section214/ST3-Travis-CI
  def get_repo(self):
    file_name = self.window.active_view().file_name()
    repoName = None
    activeBranch = None

    if file_name is not None:
      # Get the base path of the currently active file
      # and change directories to it
      file_path, file_name = os.path.split(file_name)
      os.chdir(file_path)

      try:
        repoOverride = self.get_setting('travis_project_repo', self.window.active_view(), None)
        if repoOverride is not None:
          repoName = repoOverride
        else:
          matches = subprocess.check_output(['git', 'config', '--local', '--get', 'travis.slug']).strip()
          matches = matches.decode('utf8', 'ignore').split("\n")
          repoName = ''.join(matches)

        activeBranch = subprocess.check_output(['git', 'symbolic-ref', 'HEAD']).strip()
        activeBranch = activeBranch.decode('utf8', 'ignore').replace('refs/heads/', '')
      except:
        # return {'error': 'No travis.slug in git config'}
        return {'error': ''}
    else:
      return {'error': ''}
      # print('Unsaved file')

    return {'name': repoName, 'branch': activeBranch, 'error': None}

  def make_travis_request(self, repo):
    if repo['name'] is None or repo['branch'] is None:
      return None

    repo_name_escaped = urllib.parse.quote(repo['name'], safe='')
    status = None
    latest_build = None
    token = 'token ' + self.TOKEN
    headers = {
      'Travis-API-Version': '3',
      'User-Agent': 'github@seripap/sublime-travis-ci-status',
      'Authorization': token
    }

    url = self.TRAVIS_URL + 'repo/' + repo_name_escaped + '/builds?limit=1&branch.name=' + repo['branch']

    try:
      urlReq = urllib.request.Request(url, headers=headers)
      request = urllib.request.urlopen(urlReq)

      with request as travis_json:
        travis_json = json.loads(travis_json.readall().decode('utf-8'))
        status = travis_json["builds"][0]["state"]
        latest_build = travis_json["builds"][0]["number"]
    except urllib.error.HTTPError as error:
      print('[Travis-CI API Error] ' + str(error.code) + ': ' + error.reason)
      print('[Travis-CI Debug] ' + url)
    except urllib.error.URLError as error:
      print('[Travis-CI API Error] ' + str(error.code) + ': ' + error.reason)
      print('[Travis-CI Debug] ' + url)
    except Exception as error:
      print('[Travis-CI API Error] ' + error.read().decode())
      print('[Travis-CI Debug] ' + url)

    if status is None:
      # print('[Travis-CI API Error] ' + repo['name'] + ' is not an active repository on Travis: ' + url)
      return {'status': None, 'build_number': None}

    return {'status': status, 'build_number': latest_build}

