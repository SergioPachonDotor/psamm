# This file is part of PSAMM.
#
# PSAMM is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PSAMM is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PSAMM.  If not, see <http://www.gnu.org/licenses/>.
#
# Copyright 2014-2017  Jon Lund Steffensen <jon_steffensen@uri.edu>
# Copyright 2015-2020  Keith Dufault-Thompson <keitht547@my.uri.edu>

from __future__ import unicode_literals

import time
import logging
from itertools import product

from ..command import (Command, SolverCommandMixin, MetabolicMixin,
                       ObjectiveMixin, LoopRemovalMixin, ParallelTaskMixin)
from ..util import MaybeRelative
from .. import fluxanalysis

logger = logging.getLogger(__name__)


class FluxVariabilityCommand(MetabolicMixin, SolverCommandMixin,
                             LoopRemovalMixin, ObjectiveMixin,
                             ParallelTaskMixin, Command):
    """Run flux variablity analysis on the model."""

    _supported_loop_removal = ['none', 'tfba']

    @classmethod
    def init_parser(cls, parser):
        parser.add_argument(
            '--threshold', help='Threshold of objective reaction '
                                        'flux. Can be an absolute flux value '
                                        '(0.25) or percentage of maximum '
                                        'biomass (50%)',
            type=MaybeRelative, default=MaybeRelative('100%'))
        super(FluxVariabilityCommand, cls).init_parser(parser)

    def run(self):
        """Run flux variability command"""

        # Load compound information
        def compound_name(id):
            if id not in self._model.compounds:
                return id
            return self._model.compounds[id].properties.get('name', id)

        reaction = self._get_objective()
        if not self._mm.has_reaction(reaction):
            self.fail(
                'Specified reaction is not in model: {}'.format(reaction))

        loop_removal = self._get_loop_removal_option()
        enable_tfba = loop_removal == 'tfba'
        if enable_tfba:
            solver = self._get_solver(integer=True)
        else:
            solver = self._get_solver()

        start_time = time.time()

        try:
            fba_fluxes = dict(fluxanalysis.flux_balance(
                self._mm, reaction, tfba=False, solver=solver))
        except fluxanalysis.FluxBalanceError as e:
            self.report_flux_balance_error(e)

        threshold = self._args.threshold
        if threshold.relative:
            threshold.reference = fba_fluxes[reaction]

        logger.info('Setting objective threshold to {}'.format(
            threshold))

        handler_args = (
            self._mm, solver, enable_tfba, float(threshold), reaction)
        executor = self._create_executor(
            FVATaskHandler, handler_args, cpus_per_worker=2)

        def iter_results():
            results = {}
            with executor:
                for (reaction_id, direction), value in executor.imap_unordered(
                        product(self._mm.reactions, (1, -1)), 16):
                    if reaction_id not in results:
                        results[reaction_id] = value
                        continue

                    other_value = results[reaction_id]
                    if direction == -1:
                        bounds = value, other_value
                    else:
                        bounds = other_value, value

                    yield reaction_id, bounds

            executor.join()

        for reaction_id, (lower, upper) in iter_results():
            rx = self._mm.get_reaction(reaction_id)
            rxt = rx.translated_compounds(compound_name)
            print('{}\t{}\t{}\t{}'.format(reaction_id, lower, upper, rxt))

        logger.info('Solving took {:.2f} seconds'.format(
            time.time() - start_time))


class FVATaskHandler(object):
    def __init__(self, model, solver, enable_tfba, threshold, reaction):
        self._problem = fluxanalysis.FluxBalanceProblem(model, solver)
        if enable_tfba:
            self._problem.add_thermodynamic()

        self._problem.prob.add_linear_constraints(
            self._problem.get_flux_var(reaction) >= threshold)

    def handle_task(self, reaction_id, direction):
        return self._problem.flux_bound(reaction_id, direction)
