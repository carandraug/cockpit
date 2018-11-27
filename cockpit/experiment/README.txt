This directory contains all the code needed to run experiments. Setup
of experiments is done in the gui/experiment module, but that code
ultimately just creates an Experiment subclass (e.g. ZStackExperiment)
with appropriate parameters.

actionTable.py: Describe the sequence of actions that take place as part of
  the experiment.

dataSaver.py: Handles incoming image data, saving it to disk as it comes in.

experiment.py: Base Experiment class that all other experiments subclass from.
  Never used directly on its own. The experiment.lastExperiment value holds
  the last class instance that was used to run an experiment, which can be
  useful for debugging.

structuredIllumination.py: Runs SI experiments.

zStack.py: Standard Z-stack experiment.
