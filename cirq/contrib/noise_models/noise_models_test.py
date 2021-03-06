# Copyright 2019 The Cirq Developers
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pytest

from google.protobuf.text_format import Merge

import cirq
import cirq.contrib.noise_models as ccn
from cirq.contrib.noise_models.noise_models import (
    _homogeneous_moment_is_measurements, simple_noise_from_calibration_metrics)
from cirq.devices.noise_model_test import _assert_equivalent_op_tree
from cirq.google.api import v2
from cirq import ops


def test_moment_is_measurements():
    q = cirq.LineQubit.range(2)
    circ = cirq.Circuit([cirq.X(q[0]), cirq.X(q[1]), cirq.measure(*q, key='z')])
    assert not _homogeneous_moment_is_measurements(circ[0])
    assert _homogeneous_moment_is_measurements(circ[1])


def test_moment_is_measurements_mixed1():
    q = cirq.LineQubit.range(2)
    circ = cirq.Circuit([
        cirq.X(q[0]),
        cirq.X(q[1]),
        cirq.measure(q[0], key='z'),
        cirq.Z(q[1]),
    ])
    assert not _homogeneous_moment_is_measurements(circ[0])
    with pytest.raises(ValueError) as e:
        _homogeneous_moment_is_measurements(circ[1])
    assert e.match(".*must be homogeneous: all measurements.*")


def test_moment_is_measurements_mixed2():
    q = cirq.LineQubit.range(2)
    circ = cirq.Circuit([
        cirq.X(q[0]),
        cirq.X(q[1]),
        cirq.Z(q[0]),
        cirq.measure(q[1], key='z'),
    ])
    assert not _homogeneous_moment_is_measurements(circ[0])
    with pytest.raises(ValueError) as e:
        _homogeneous_moment_is_measurements(circ[1])
    assert e.match(".*must be homogeneous: all measurements.*")


def test_depol_noise():
    noise_model = ccn.DepolarizingNoiseModel(depol_prob=0.005)
    qubits = cirq.LineQubit.range(2)
    moment = cirq.Moment([
        cirq.X(qubits[0]),
        cirq.Y(qubits[1]),
    ])
    noisy_mom = noise_model.noisy_moment(moment, system_qubits=qubits)
    assert len(noisy_mom) == 2
    assert noisy_mom[0] == moment
    for g in noisy_mom[1]:
        assert isinstance(g.gate, cirq.DepolarizingChannel)


# Composes depolarization noise with readout noise.
def test_readout_noise_after_moment():
    program = cirq.Circuit()
    qubits = cirq.LineQubit.range(3)
    program.append([
        cirq.H(qubits[0]),
        cirq.CNOT(qubits[0], qubits[1]),
        cirq.CNOT(qubits[1], qubits[2])
    ])
    program.append([
        cirq.measure(qubits[0], key='q0'),
        cirq.measure(qubits[1], key='q1'),
        cirq.measure(qubits[2], key='q2')
    ],
                   strategy=cirq.InsertStrategy.NEW_THEN_INLINE)

    # Use noise model to generate circuit
    depol_noise = ccn.DepolarizingNoiseModel(depol_prob=0.01)
    readout_noise = ccn.ReadoutNoiseModel(bitflip_prob=0.05)
    noisy_circuit = cirq.Circuit(depol_noise.noisy_moments(program, qubits))
    noisy_circuit = cirq.Circuit(
        readout_noise.noisy_moments(noisy_circuit, qubits))

    # Insert channels explicitly
    true_noisy_program = cirq.Circuit()
    true_noisy_program.append([cirq.H(qubits[0])])
    true_noisy_program.append([
        cirq.DepolarizingChannel(0.01).on(q).with_tags(ops.VirtualTag())
        for q in qubits
    ],
                              strategy=cirq.InsertStrategy.NEW_THEN_INLINE)
    true_noisy_program.append([cirq.CNOT(qubits[0], qubits[1])])
    true_noisy_program.append([
        cirq.DepolarizingChannel(0.01).on(q).with_tags(ops.VirtualTag())
        for q in qubits
    ],
                              strategy=cirq.InsertStrategy.NEW_THEN_INLINE)
    true_noisy_program.append([cirq.CNOT(qubits[1], qubits[2])])
    true_noisy_program.append([
        cirq.DepolarizingChannel(0.01).on(q).with_tags(ops.VirtualTag())
        for q in qubits
    ],
                              strategy=cirq.InsertStrategy.NEW_THEN_INLINE)
    true_noisy_program.append([
        cirq.BitFlipChannel(0.05).on(q).with_tags(ops.VirtualTag())
        for q in qubits
    ])
    true_noisy_program.append([
        cirq.measure(qubits[0], key='q0'),
        cirq.measure(qubits[1], key='q1'),
        cirq.measure(qubits[2], key='q2')
    ])
    _assert_equivalent_op_tree(true_noisy_program, noisy_circuit)


# Composes depolarization, damping, and readout noise (in that order).
def test_decay_noise_after_moment():
    program = cirq.Circuit()
    qubits = cirq.LineQubit.range(3)
    program.append([
        cirq.H(qubits[0]),
        cirq.CNOT(qubits[0], qubits[1]),
        cirq.CNOT(qubits[1], qubits[2])
    ])
    program.append([
        cirq.measure(qubits[0], key='q0'),
        cirq.measure(qubits[1], key='q1'),
        cirq.measure(qubits[2], key='q2')
    ],
                   strategy=cirq.InsertStrategy.NEW_THEN_INLINE)

    # Use noise model to generate circuit
    depol_noise = ccn.DepolarizingNoiseModel(depol_prob=0.01)
    readout_noise = ccn.ReadoutNoiseModel(bitflip_prob=0.05)
    damping_noise = ccn.DampedReadoutNoiseModel(decay_prob=0.02)
    noisy_circuit = cirq.Circuit(depol_noise.noisy_moments(program, qubits))
    noisy_circuit = cirq.Circuit(
        damping_noise.noisy_moments(noisy_circuit, qubits))
    noisy_circuit = cirq.Circuit(
        readout_noise.noisy_moments(noisy_circuit, qubits))

    # Insert channels explicitly
    true_noisy_program = cirq.Circuit()
    true_noisy_program.append([cirq.H(qubits[0])])
    true_noisy_program.append([
        cirq.DepolarizingChannel(0.01).on(q).with_tags(ops.VirtualTag())
        for q in qubits
    ],
                              strategy=cirq.InsertStrategy.NEW_THEN_INLINE)
    true_noisy_program.append([cirq.CNOT(qubits[0], qubits[1])])
    true_noisy_program.append([
        cirq.DepolarizingChannel(0.01).on(q).with_tags(ops.VirtualTag())
        for q in qubits
    ],
                              strategy=cirq.InsertStrategy.NEW_THEN_INLINE)
    true_noisy_program.append([cirq.CNOT(qubits[1], qubits[2])])
    true_noisy_program.append([
        cirq.DepolarizingChannel(0.01).on(q).with_tags(ops.VirtualTag())
        for q in qubits
    ],
                              strategy=cirq.InsertStrategy.NEW_THEN_INLINE)
    true_noisy_program.append([
        cirq.AmplitudeDampingChannel(0.02).on(q).with_tags(ops.VirtualTag())
        for q in qubits
    ])
    true_noisy_program.append([
        cirq.BitFlipChannel(0.05).on(q).with_tags(ops.VirtualTag())
        for q in qubits
    ])
    true_noisy_program.append([
        cirq.measure(qubits[0], key='q0'),
        cirq.measure(qubits[1], key='q1'),
        cirq.measure(qubits[2], key='q2')
    ])
    _assert_equivalent_op_tree(true_noisy_program, noisy_circuit)


# Fake calibration data object.
_CALIBRATION_DATA = Merge(
    """
    timestamp_ms: 1579214873,
    metrics: [{
        name: 'xeb',
        targets: ['0_0', '0_1'],
        values: [{
            double_val: .9999
        }]
    }, {
        name: 'xeb',
        targets: ['0_0', '1_0'],
        values: [{
            double_val: .9998
        }]
    }, {
        name: 'single_qubit_rb_total_error',
        targets: ['q0_0'],
        values: [{
            double_val: .001
        }]
    }, {
        name: 'single_qubit_rb_total_error',
        targets: ['q0_1'],
        values: [{
            double_val: .002
        }]
    }, {
        name: 'single_qubit_rb_total_error',
        targets: ['q1_0'],
        values: [{
            double_val: .003
        }]
    }]
""", v2.metrics_pb2.MetricsSnapshot())


def test_per_qubit_noise_from_data():
    # Generate the noise model from calibration data.
    calibration = cirq.google.Calibration(_CALIBRATION_DATA)
    noise_model = simple_noise_from_calibration_metrics(calibration)

    # Create the circuit and apply the noise model.
    qubits = [cirq.GridQubit(0, 0), cirq.GridQubit(0, 1), cirq.GridQubit(1, 0)]
    program = cirq.Circuit(
        cirq.Moment([cirq.H(qubits[0])]),
        cirq.Moment([cirq.CNOT(qubits[0], qubits[1])]),
        cirq.Moment([cirq.CNOT(qubits[0], qubits[2])]),
        cirq.Moment([
            cirq.measure(qubits[0], key='q0'),
            cirq.measure(qubits[1], key='q1'),
            cirq.measure(qubits[2], key='q2')
        ]))
    noisy_circuit = cirq.Circuit(noise_model.noisy_moments(program, qubits))

    # Insert channels explicitly to construct expected output.
    expected_program = cirq.Circuit(
        cirq.Moment([cirq.H(qubits[0])]),
        cirq.Moment([cirq.DepolarizingChannel(0.001).on(qubits[0])]),
        cirq.Moment([cirq.CNOT(qubits[0], qubits[1])]),
        cirq.Moment([
            cirq.DepolarizingChannel(0.001).on(qubits[0]),
            cirq.DepolarizingChannel(0.002).on(qubits[1])
        ]), cirq.Moment([cirq.CNOT(qubits[0], qubits[2])]),
        cirq.Moment([
            cirq.DepolarizingChannel(0.001).on(qubits[0]),
            cirq.DepolarizingChannel(0.003).on(qubits[2])
        ]),
        cirq.Moment([
            cirq.measure(qubits[0], key='q0'),
            cirq.measure(qubits[1], key='q1'),
            cirq.measure(qubits[2], key='q2')
        ]))
    _assert_equivalent_op_tree(expected_program, noisy_circuit)
