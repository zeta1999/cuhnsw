# Copyright (c) 2020 Jisang Yoon
# All rights reserved.
#
# This source code is licensed under the Apache 2.0 license found in the
# LICENSE file in the root directory of this source tree.

# Adapted from https://github.com/rmcgibbo/npcuda-example and
# https://github.com/cupy/cupy/blob/master/cupy_setup_build.py
# pylint: disable=fixme,access-member-before-definition
# pylint: disable=attribute-defined-outside-init,arguments-differ
import logging
import os
import sys

from distutils import ccompiler, errors, msvccompiler, unixccompiler
from setuptools.command.build_ext import build_ext as setuptools_build_ext

HALF_PRECISION = False

def find_in_path(name, path):
  "Find a file in a search path"
  # adapted fom http://code.activestate.com/
  # recipes/52224-find-a-file-given-a-search-path/
  for _dir in path.split(os.pathsep):
    binpath = os.path.join(_dir, name)
    if os.path.exists(binpath):
      return os.path.abspath(binpath)
  return None


def locate_cuda():
  """Locate the CUDA environment on the system
  If a valid cuda installation is found
  this returns a dict with keys 'home', 'nvcc', 'include',
  and 'lib64' and values giving the absolute path to each directory.
  Starts by looking for the CUDAHOME env variable.
  If not found, everything is based on finding
  'nvcc' in the PATH.
  If nvcc can't be found, this returns None
  """
  nvcc_bin = 'nvcc'
  if sys.platform.startswith("win"):
    nvcc_bin = 'nvcc.exe'

  # check env variables CUDA_HOME, CUDAHOME, CUDA_PATH.
  found = False
  for env_name in ['CUDA_PATH', 'CUDAHOME', 'CUDA_HOME']:
    if env_name not in os.environ:
      continue
    found = True
    home = os.environ[env_name]
    nvcc = os.path.join(home, 'bin', nvcc_bin)
    break
  if not found:
    # otherwise, search the PATH for NVCC
    nvcc = find_in_path(nvcc_bin, os.environ['PATH'])
    if nvcc is None:
      logging.warning('The nvcc binary could not be located in your '
              '$PATH. Either add it to '
              'your path, or set $CUDA_HOME to enable CUDA extensions')
      return None
    home = os.path.dirname(os.path.dirname(nvcc))

  cudaconfig = {'home': home,
          'nvcc': nvcc,
          'include': os.path.join(home, 'include'),
          'lib64':   os.path.join(home, 'lib64')}
  post_args = [
    "-arch=sm_52",
    "-gencode=arch=compute_52,code=sm_52",
    "-gencode=arch=compute_60,code=sm_60",
    "-gencode=arch=compute_61,code=sm_61",
    "-gencode=arch=compute_70,code=sm_70",
    "-gencode=arch=compute_75,code=sm_75",
    "-gencode=arch=compute_80,code=sm_80",
    "-gencode=arch=compute_86,code=sm_86",
    "-gencode=arch=compute_86,code=compute_86",
    '--ptxas-options=-v', '-O2']
  if HALF_PRECISION:
    post_args = [flag for flag in post_args if "52" not in flag]

  if sys.platform == "win32":
    cudaconfig['lib64'] = os.path.join(home, 'lib', 'x64')
    post_args += ['-Xcompiler', '/MD', '-std=c++14',  "-Xcompiler", "/openmp"]
    if HALF_PRECISION:
      post_args += ["-Xcompiler", "/D HALF_PRECISION"]
  else:
    post_args += ['-c', '--compiler-options', "'-fPIC'",
                  "--compiler-options", "'-std=c++14'"]
    if HALF_PRECISION:
      post_args += ["--compiler-options", "'-D HALF_PRECISION'"]
  for k, val in cudaconfig.items():
    if not os.path.exists(val):
      logging.warning('The CUDA %s path could not be located in %s', k, val)
      return None

  cudaconfig['post_args'] = post_args
  return cudaconfig


# This code to build .cu extensions with nvcc is taken from cupy:
# https://github.com/cupy/cupy/blob/master/cupy_setup_build.py
class _UnixCCompiler(unixccompiler.UnixCCompiler):
  src_extensions = list(unixccompiler.UnixCCompiler.src_extensions)
  src_extensions.append('.cu')

  def _compile(self, obj, src, ext, cc_args, extra_postargs, pp_opts):
    # For sources other than CUDA C ones, just call the super class method.
    if os.path.splitext(src)[1] != '.cu':
      return unixccompiler.UnixCCompiler._compile(
        self, obj, src, ext, cc_args, extra_postargs, pp_opts)

    # For CUDA C source files, compile them with NVCC.
    _compiler_so = self.compiler_so
    try:
      nvcc_path = CUDA['nvcc']
      post_args = CUDA['post_args']
      # TODO? base_opts = build.get_compiler_base_options()
      self.set_executable('compiler_so', nvcc_path)

      return unixccompiler.UnixCCompiler._compile(
        self, obj, src, ext, cc_args, post_args, pp_opts)
    finally:
      self.compiler_so = _compiler_so


class _MSVCCompiler(msvccompiler.MSVCCompiler):
  _cu_extensions = ['.cu']

  src_extensions = list(unixccompiler.UnixCCompiler.src_extensions)
  src_extensions.extend(_cu_extensions)

  def _compile_cu(self, sources, output_dir=None, macros=None,
          include_dirs=None, debug=0, extra_preargs=None,
          extra_postargs=None, depends=None):
    # Compile CUDA C files, mainly derived from UnixCCompiler._compile().
    macros, objects, extra_postargs, pp_opts, _build = \
      self._setup_compile(output_dir, macros, include_dirs, sources,
                depends, extra_postargs)

    compiler_so = CUDA['nvcc']
    cc_args = self._get_cc_args(pp_opts, debug, extra_preargs)
    post_args = CUDA['post_args']

    for obj in objects:
      try:
        src, _ = _build[obj]
      except KeyError:
        continue
      try:
        self.spawn([compiler_so] + cc_args + [src, '-o', obj] + post_args)
      except errors.DistutilsExecError as e:
        raise errors.CompileError(str(e))

    return objects

  def compile(self, sources, **kwargs):
    # Split CUDA C sources and others.
    cu_sources = []
    other_sources = []
    for source in sources:
      if os.path.splitext(source)[1] == '.cu':
        cu_sources.append(source)
      else:
        other_sources.append(source)

    # Compile source files other than CUDA C ones.
    other_objects = msvccompiler.MSVCCompiler.compile(
      self, other_sources, **kwargs)

    # Compile CUDA C sources.
    cu_objects = self._compile_cu(cu_sources, **kwargs)

    # Return compiled object filenames.
    return other_objects + cu_objects


class CudaBuildExt(setuptools_build_ext):
  """Custom `build_ext` command to include CUDA C source files."""

  def run(self):
    if CUDA is not None:
      def wrap_new_compiler(func):
        def _wrap_new_compiler(*args, **kwargs):
          try:
            return func(*args, **kwargs)
          except errors.DistutilsPlatformError:
            if sys.platform != 'win32':
              CCompiler = _UnixCCompiler
            else:
              CCompiler = _MSVCCompiler
            return CCompiler(
              None, kwargs['dry_run'], kwargs['force'])
        return _wrap_new_compiler
      ccompiler.new_compiler = wrap_new_compiler(ccompiler.new_compiler)
      # Intentionally causes DistutilsPlatformError in
      # ccompiler.new_compiler() function to hook.
      self.compiler = 'nvidia'

    setuptools_build_ext.run(self)


CUDA = locate_cuda()
assert CUDA is not None
BUILDEXT = CudaBuildExt if CUDA else setuptools_build_ext