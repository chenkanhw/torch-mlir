# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
# Also available under a BSD-style license. See LICENSE.

import sys
from typing import Any
from io import StringIO
import os
import tempfile

import numpy as np
import torch

from torch_mlir_e2e_test.linalg_on_tensors_backends.abc import LinalgOnTensorsBackend
from torch_mlir_e2e_test.torchscript.framework import TestConfig, Trace, TraceItem
from .utils import (
    recursively_convert_to_numpy,
    recursively_convert_from_numpy,
    convert_torchscript_module_to_torch_backend_contract_mlir,
    run_pipeline_with_repro_report
)


class LinalgOnTensorsBackendTestConfig(TestConfig):
    """Base class for TestConfig's that are implemented with linalg-on-tensors.

    This class handles all the common lowering that torch-mlir does before
    reaching the linalg-on-tensors abstraction level.
    """
    def __init__(self, backend: LinalgOnTensorsBackend):
        super().__init__()
        self.backend = backend

    def compile(self, program: torch.nn.Module) -> Any:

        module = convert_torchscript_module_to_torch_backend_contract_mlir(
            program)

        run_pipeline_with_repro_report(
            module,
            "torch-backend-to-linalg-on-tensors-backend-pipeline",
            "Lower Torch Backend IR -> Linalg-on-Tensors Backend IR",
            program.__class__.__name__)

        try:
            sys.stderr = StringIO()
            asm_for_error_report = module.operation.get_asm(
                large_elements_limit=10, enable_debug_info=True)
            return self.backend.compile(module)
        except Exception as e:
            filename = os.path.join(tempfile.gettempdir(),
                                    program.__class__.__name__ + ".mlir")
            with open(filename, 'w') as f:
                f.write(asm_for_error_report)
            raise Exception(f"""
Linalg-on-Tensors Backend lowering for {self.backend.__class__.__name__} failed with the following diagnostics:
## Exception:
{e}

## Stderr:
{sys.stderr.getvalue()}

## Input IR has been saved in {filename}
""") from None
        finally:
            sys.stderr = sys.__stderr__


    def run(self, artifact: Any, trace: Trace) -> Trace:
        backend_module = self.backend.load(artifact)
        result: Trace = []
        for item in trace:
            numpy_inputs = recursively_convert_to_numpy(item.inputs)
            outputs = getattr(backend_module, item.symbol)(*numpy_inputs)
            output = recursively_convert_from_numpy(outputs)
            result.append(
                TraceItem(symbol=item.symbol,
                          inputs=item.inputs,
                          output=output))
        return result