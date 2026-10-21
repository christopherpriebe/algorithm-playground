Configuration file
==================

A configuration file describes implementations so that you can refer to them
by name instead of by path or command text. It is meant for a repository that
holds your own solutions: put an ``algorithm-playground.toml`` at its root and
the harness picks it up automatically.

Discovery
---------

``test``, ``benchmark``, ``debug``, and ``list`` read the configuration file
named by ``--configuration PATH``. Without that option they look for
``algorithm-playground.toml`` in the **current directory** and then in each
parent directory in turn, so the commands work from any subdirectory of a
solutions repository. The search stops at the first directory that contains a
``.git`` entry (the root of the repository; that directory is still searched)
and at the root of the file system. The implementations run relative to the
directory of the file that was found, not to the current directory. A file named
explicitly must exist and be valid, otherwise the command exits with code ``2``.

When no implementation is named on the command line, ``test`` and
``benchmark`` use every implementation the file configures for the problem.
Naming an implementation (positional argument or ``--command``) replaces that
default; see :doc:`cli`.

Format
------

The file is TOML. It has two optional top-level keys for problems that live
outside this package (see `Problems from your own modules`_) and one
``[[implementations]]`` table per implementation:

.. code-block:: toml

   [[implementations]]
   name = "merge-sort-c"                  # required
   problem = "sorting"                    # required
   command = "./build/merge_sort"         # required
   build_command = "make build/merge_sort" # optional
   working_directory = "."                # optional
   inherit_environment = false            # optional
   environment = { PYTHONPATH = "{configuration_directory}/helpers" }  # optional
   timeout_seconds = 120                  # optional

``name``
   The name used on the command line and in every table and report. Required,
   a non-empty string, unique among the entries for the same problem. Two
   entries for different problems may share a name.

``problem``
   The registered problem the implementation solves, for example ``sorting``
   (see ``algorithm-playground list``). Required. Once the problem modules are
   loaded, a name that no registered problem has is a configuration error.

``command``
   What to run; the harness appends the input, output, and optional trace
   paths (see :doc:`executable-contract`). Required. Either a string, split
   into arguments with shell-style quoting (``"java -jar 'My Sort.jar'"``), or
   a list of strings that is used as given (``["java", "-jar", "My Sort.jar"]``).
   Use the list form when an argument contains spaces. There is no shell:
   variable expansion, pipes, and globbing do not happen. Relative paths are
   resolved against ``working_directory``.

``build_command``
   A command that prepares the implementation, in the same two forms as
   ``command``. Optional. It runs once per invocation before the implementation
   is used, in ``working_directory``, unless ``--no-build`` is given.

``working_directory``
   The directory the build and the implementation run in. Optional, a string
   relative to the directory of the configuration file (absolute paths are
   allowed). It defaults to the directory containing the configuration file.

``inherit_environment``
   ``true`` to give the implementation and its build the full environment of
   the ``algorithm-playground`` process instead of the minimal one described in
   :doc:`executable-contract`. Optional, default ``false``.

``environment``
   A table of variables to set for the implementation and for its build, on top
   of the minimal environment or, with ``inherit_environment``, of the inherited
   one (a variable of the table wins over an inherited one with the same name).
   Optional. Every value is a string, and ``{configuration_directory}`` in a
   value is replaced by the absolute directory of the configuration file, so a
   value does not depend on where the command is run from. This is how a helper
   module in the solutions repository is put on the import path of a Python
   implementation without handing it the whole environment:

   .. code-block:: toml

      environment = { PYTHONPATH = "{configuration_directory}/helpers" }

   No other text in braces is touched. The values appear in the file only; the
   JSON reports do not repeat them.

``timeout_seconds``
   How long one run of this implementation may take, in seconds. Optional, a
   positive number. It replaces the ``--timeout`` of the command for this
   implementation (and for the runs of a shrink and of the counting of
   operations), so a slow Java or interpreted solution can have more time than
   the others. The builds have their own, fixed limit of five minutes.

Problems from your own modules
------------------------------

A repository of solutions can also hold the problems themselves, or depend on
a package that provides them. Two top-level keys, placed before the first
``[[implementations]]``, make such problems available:

.. code-block:: toml

   python_paths = ["."]
   problem_modules = ["solutions_problems.graphs"]

``python_paths``
   Directories added to the front of Python's import path, so that the
   modules below can be imported. Optional, a list of strings, each relative to
   the directory of the configuration file (absolute paths are allowed). Each
   must be an existing directory. They stay on the import path for the whole
   command, so a problem can import its neighbors later, from inside a hook.

``problem_modules``
   Names of Python modules to import. Importing a module runs the
   ``@register_problem`` decorators in it, which makes the problems it defines
   available to every command, exactly like the built-in ones. Optional, a list
   of dotted module names.

Both are applied before anything else is looked up, so the ``problem`` of an
implementation may name a problem defined in these modules. A module that
cannot be imported (a typo, a missing dependency, an error while importing it)
is a configuration error that names the file and the module, and exits with
code ``2``. ``--problem-module NAME`` on the command line adds more modules,
and installed packages can contribute problems without any configuration
through entry points. All three routes are described in
:doc:`writing-a-problem`; ``algorithm-playground list`` shows where each
problem came from.

Any other key, in an entry or at the top level, is an error, so typos are
caught instead of silently ignored. The error lists the allowed keys and notes
that a file written for a newer algorithm-playground needs that newer version.

The file is read as UTF-8; a leading byte order mark, which some editors add,
is ignored.

Example: a solutions repository
-------------------------------

A repository with C, Python, and Java solutions to sorting:

.. code-block:: text

   my-solutions/
   ├── algorithm-playground.toml
   ├── Makefile
   ├── c/
   │   ├── merge_sort.c
   │   └── quick_sort.c
   ├── python/
   │   └── heap_sort.py
   └── java/
       └── Sort.java

.. code-block:: toml

   # my-solutions/algorithm-playground.toml

   [[implementations]]
   name = "merge-sort-c"
   problem = "sorting"
   command = "./build/merge_sort"
   build_command = "make build/merge_sort"

   [[implementations]]
   name = "quick-sort-c"
   problem = "sorting"
   command = "./build/quick_sort"
   build_command = "make build/quick_sort"

   [[implementations]]
   name = "heap-sort-python"
   problem = "sorting"
   command = "python3 python/heap_sort.py"

   [[implementations]]
   name = "sort-java"
   problem = "sorting"
   command = ["java", "-cp", "build/java", "Sort"]
   build_command = ["javac", "-d", "build/java", "java/Sort.java"]
   inherit_environment = true             # find the JDK through JAVA_HOME
   timeout_seconds = 120                  # the JVM is slow to start on a busy machine

   [[implementations]]
   name = "radix-sort-python"
   problem = "sorting"
   command = "python3 python/radix_sort.py"
   environment = { PYTHONPATH = "{configuration_directory}/python/helpers" }

From the repository root:

.. code-block:: console

   $ algorithm-playground list                         # problems and configured implementations
   $ algorithm-playground test sorting                 # every sorting implementation
   $ algorithm-playground benchmark sorting --sizes 1000,100000
   $ algorithm-playground benchmark sorting merge-sort-c heap-sort-python \
       --reference merge-sort-c
   $ algorithm-playground debug sorting merge-sort-c --size 16

``list`` shows the configured implementations next to the registered problems.
Inside ``my-solutions/c`` the same commands work, because the file is found in
a parent directory; from outside the repository, pass it explicitly with
``--configuration my-solutions/algorithm-playground.toml``. Either way the
entries run relative to the directory of the configuration file.

Errors
------

A configuration problem is reported, on standard error, with the file name and
the offending entry (its index and name) and exits with code ``2``. The file
name is shown relative to the current directory when the file is inside it.
The checks are: the file must exist and be valid TOML; the only top-level keys
are ``implementations``, an array of tables, ``problem_modules``, a list of
module names, and ``python_paths``, a list of existing directories; each entry
has a ``name``, a ``problem``, and a ``command``; ``command`` and
``build_command`` are non-empty strings (that parse as shell-style text) or
non-empty lists of non-empty strings; ``working_directory`` is a non-empty
string; ``inherit_environment`` is a boolean; ``environment`` is a table of
variable names (non-empty, without ``=``) to strings; ``timeout_seconds`` is a
finite positive number; a name is not used twice for the same problem; every ``problem_modules`` entry can be imported; and every
``problem`` is registered once the modules are loaded.
