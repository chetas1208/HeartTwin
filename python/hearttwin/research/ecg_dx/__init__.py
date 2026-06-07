"""Research ECG diagnostic classifier (PTB-XL diagnostic superclasses).

Experimental. Not a medical device, not for diagnosis or treatment decisions.
Outputs class probabilities for an ECG superclass screening task and is evaluated
by benchmark/run_dx_benchmark.py against PTB-XL labels.
"""

from .classifier import EcgDxClassifier, SUPERCLASSES, DISCLAIMER  # noqa: F401
