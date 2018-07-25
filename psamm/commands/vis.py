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
# Copyright 2018-2018  Ke Zhang <kzhang@my.uri.edu>

from __future__ import unicode_literals

import logging
from ..command import (LoopRemovalMixin, ObjectiveMixin, SolverCommandMixin,
                       MetabolicMixin, Command, FilePrefixAppendAction, CommandError)
import csv
from ..reaction import Direction
from six import text_type, iteritems, itervalues, iterkeys
from .. import findprimarypairs
from ..formula import Formula, Atom, ParseError
from .. import graph
from collections import Counter
from .tableexport import _encode_value
import argparse
from .. import fluxanalysis
from collections import defaultdict, namedtuple
try:
    from graphviz import render
except ImportError:
    render = None

import subprocess

import unittest

logger = logging.getLogger(__name__)

REACTION_COLOR = '#ccebc5'
COMPOUND_COLOR = '#fbb4ae'
ACTIVE_COLOR = '#b3cde3'    # exchange reaction  color
ALT_COLOR = '#f4fc55'       # biomass reaction color
RXN_COMBINED_COLOR = '#fc9a44'
CPD_ONLY_IN_BIO = '#82e593'
CPD_ONLY_IN_EXC = '#5a95f4'

from psamm.reaction import Compound


def cpds_properties(cpd, compound, detail): # cpd=Compound object, compound = CompoundEntry object
    """define compound nodes label"""
    compound_set = set()
    compound_set.update(compound.properties)
    if detail is not None:
        cpd_detail = []
        for prop in detail[0]:
            if prop in compound_set:
                cpd_detail.append(str(prop))
        pre_label = '\n'.join(_encode_value(compound.properties[value]) for value in cpd_detail if value != 'id')
        label = '{}\n{}'.format(str(cpd), pre_label)
    else:
        label = str(cpd)
    return label


def rxns_properties(reaction, detail, reaction_flux):
    """define reaction nodes label"""
    reaction_set = set()
    reaction_set.update(reaction.properties)
    if detail is not None:
        rxn_detail = []
        for prop in detail[0]:
            if prop in reaction_set:
                rxn_detail.append(str(prop))
        label = '\n'.join(_encode_value(reaction.properties[value])
                          for value in rxn_detail)
        if len(reaction_flux) > 0:
            if reaction.id in iterkeys(reaction_flux):
                label = '{}\n{}'.format(label, reaction_flux[reaction.id])
    else:
        if len(reaction_flux) > 0:
            if reaction.id in reaction_flux:
                label = '{}\n{}'.format(reaction.id, reaction_flux[reaction.id])
            else:
                label = reaction.id
        else:
            label = reaction.id

    return label


def primary_element(element):
    """allow both lower and upper case for one-letter element """
    if element is not None:
        if element in ['c', 'h', 'o', 'n', 'p', 's', 'k', 'b', 'f', 'v', 'y', 'i', 'w']:
            return element.upper()
        else:
            return element


def make_edge_values(reaction_flux, mm, compound_formula, element, split_map, cpair_dict):
    """set edge_values according to reaction fluxes"""
    edge_values = {}
    if len(reaction_flux) > 0:
        for reaction in mm.reactions:
            rx = mm.get_reaction(reaction)
            if reaction in reaction_flux:
                flux = reaction_flux[reaction]
                if abs(flux) < 1e-9:
                    continue

                if flux > 0:
                    for compound, value in rx.right:  # value=stoichiometry
                        if Atom(element) in compound_formula[compound.name]:
                            edge_values[reaction, compound] = (flux * float(value))
                    for compound, value in rx.left:
                        if Atom(element) in compound_formula[compound.name]:
                            edge_values[compound, reaction] = (flux * float(value))
                else:
                    for compound, value in rx.left:
                        if Atom(element) in compound_formula[compound.name]:
                            edge_values[reaction, compound] = (- flux * float(value))
                    for compound, value in rx.right:
                        if Atom(element) in compound_formula[compound.name]:
                            edge_values[compound, reaction] = (- flux * float(value))

        if split_map is not True:
            remove_edges = set()
            for (c1, c2), rxns in iteritems(cpair_dict):
                if len(rxns.forward) > 1:
                    if all(r not in reaction_flux for r in rxns.forward):
                        continue
                    else:
                        x_forward_c1, x_forward_c2 = 0, 0
                        for r in rxns.forward:
                            if r in reaction_flux:
                                # y_1 = edge_values[(c1, r)]
                                # y_2 = edge_values[(r, c2)]
                                x_forward_c1 += edge_values[(c1, r)]
                                x_forward_c2 += edge_values[(r, c2)]
                                remove_edges.add((c1, r))
                                remove_edges.add((r, c2))
                        edge_values[(c1, tuple(rxns.forward))] = x_forward_c1
                        edge_values[(tuple(rxns.forward), c2)] = x_forward_c2
                if len(rxns.back) > 1:
                    if all(r not in reaction_flux for r in rxns.back) :
                        continue
                    else:
                        x_back_c1, x_back_c2 = 0, 0
                        for r in rxns.back:
                            if r in reaction_flux:
                                # y_1 = edge_values[(r, c1)]
                                # y_2 = edge_values[(c2, r)]
                                x_back_c1 += edge_values[(r, c1)]
                                x_back_c2 += edge_values[(c2, r)]
                                remove_edges.add((r, c1))
                                remove_edges.add((c2, r))
                        edge_values[(tuple(rxns.back), c1)] = x_back_c1
                        edge_values[(c2, tuple(rxns.back))] = x_back_c2
            for edge in remove_edges:
                del edge_values[edge]

    # for (a, b), v in iteritems(edge_values):
    #     print('{}\t{}\t{}'.format(a, b, v))

                    # if split_map is not True:
    #     for (c1, c2), rxns in cpair_dict:  # rxns=[ [forward_rxns], [back_rxns], [bidir_rxns] ]
    #         for rlist in rxns:
    #             if len(rlist) > 1:
    #             x_for = 0
    #             for j in forward:
    #                 y = edge_values.get(c1, j)
    #                 if y is not None:
    #                     x_for += y
    #         if len(fowrard) > 1:
    #             x_rev = 0
    #             for j in forward:
    #                 y_2 = edge_values.get(c1, j)
    #                 if y_2 is not None:
    #                     x_rev += y_2
    #         if len(bid) > 1:
    #             x_bid = 0
    #             for j in bid:
    #                 y_3 = edge_values.get(c1, j)
    #                 if y_3 < 0:
    #                     x_rev += y_3
    #
    #                 if y_3 > 0:
    #                     x_for += y_3

    return edge_values


def make_filter_dict(model, mm, method, element, compound_formula, cpd_object, exclude_cpairs, exclude_rxns):
    """create a dictionary of reaction id(key) and a list of related compound pairs(value)"""
    filter_dict = {}
    if method == 'fpp':
        # def iter_reactions():
        #     """yield reactions that can applied to fpp"""
        fpp_rxns, rxns_no_equation, rxns_no_formula = set(), set(), []
        for reaction in model.reactions:
            if (reaction.id in model.model and
                    reaction.id not in exclude_rxns):
                if reaction.equation is None:
                    rxns_no_equation.add(reaction.id)
                    continue

                if any(c.name not in compound_formula for c, _ in reaction.equation.compounds):
                    rxns_no_formula.append(reaction.id)
                    continue

                fpp_rxns.add(reaction)

        if len(rxns_no_equation) > 0:
            logger.warning(
                '{} reactions have no reaction equation, fix them or try no-fpp method. '
                'These reactions contain {}'.format(len(rxns_no_equation), rxns_no_equation))
            quit()

        if len(rxns_no_formula) > 0:
            logger.warning(
                '{} reactions have compounds with undefined formula, fix them or try no-fpp method.'
                'These reactions contain {}'.format(len(rxns_no_formula), rxns_no_formula))
            quit()

        split_reaction = True
        reaction_pairs = [(r.id, r.equation) for r in fpp_rxns]
        element_weight = findprimarypairs.element_weight
        fpp_dict, _ = findprimarypairs.predict_compound_pairs_iterated(reaction_pairs, compound_formula,
                                                                       element_weight=element_weight)

        for rxn_id, fpp_pairs in iteritems(fpp_dict):
            compound_pairs = []
            for cpd_pair, transfer in iteritems(fpp_pairs[0]):
                if cpd_pair not in exclude_cpairs:
                    if element is None:
                        compound_pairs.append(cpd_pair)
                    else:
                        if any(Atom(primary_element(element)) in k for k in transfer):
                            compound_pairs.append(cpd_pair)
            filter_dict[rxn_id] = compound_pairs

    elif method == 'no-fpp':
        split_reaction = False
        for rxn_id in mm.reactions:
            if rxn_id != model.biomass_reaction:
                rx = mm.get_reaction(rxn_id)
                cpairs = []
                for c1, _ in rx.left:
                    for c2, _ in rx.right:
                        if (c1, c2) not in exclude_cpairs:
                            if element is not None:
                                if Atom(primary_element(element)) in compound_formula[c1.name]:
                                    if Atom(primary_element(element)) in compound_formula[c2.name]:
                                        cpairs.append((c1, c2))
                            else:
                                cpairs.append((c1, c2))
                filter_dict[rxn_id] = cpairs
    else:
        split_reaction = True
        try:
            with open(method, 'r') as f:
                cpair_list, rxn_list = [], []
                for row in csv.reader(f, delimiter=str(u'\t')):
                    if (cpd_object[row[1]], cpd_object[row[2]]) not in exclude_cpairs:
                        if element is None:
                            cpair_list.append((cpd_object[row[1]], cpd_object[row[2]]))
                            rxn_list.append(row[0])
                        else:
                            if Atom(primary_element(element)) in Formula.parse(row[3]).flattened():
                                cpair_list.append((cpd_object[row[1]], cpd_object[row[2]]))
                                rxn_list.append(row[0])

                filter_dict = defaultdict(list)
                for r, cpair in zip(rxn_list, cpair_list):
                    filter_dict[r].append(cpair)
        except:
            if IOError:
                logger.error(' Invalid file path, no such file or directory : {}' .format(method))
            quit()

    return filter_dict, split_reaction


class VisualizationCommand(MetabolicMixin, ObjectiveMixin,
                           SolverCommandMixin, Command, LoopRemovalMixin, FilePrefixAppendAction):
    """Run visualization command on the model."""

    @classmethod
    def init_parser(cls, parser):
        parser.add_argument(
            '--method',type=text_type,
            default='fpp', help='Compound pair prediction method')
        parser.add_argument(
            '--exclude', metavar='reaction', type=text_type, default=[],
            action=FilePrefixAppendAction,
            help='Reaction to exclude (e.g. biomass reactions or macromolecule synthesis)')
        parser.add_argument(
            '--fba', action='store_true',
            help='visualize reaction flux')
        parser.add_argument(
            '--element', type=text_type, default='C',
            help='Primary element flow')
        parser.add_argument(
            '--detail', type=text_type, default=None, action='append', nargs='+',
            help='Reaction and compound properties showed on nodes label')
        parser.add_argument(
            '--subset', type=argparse.FileType('r'), default=None,
            help='Reactions designated to visualize')
        parser.add_argument(
            '--color', type=argparse.FileType('r'), default=None, nargs='+',
            help='Customize color of reaction and compound nodes ')
        parser.add_argument(
            '--Image', type=text_type, default=None, help='generate image file directly')
        parser.add_argument(
            '--exclude-pairs', type=argparse.FileType('r'), default=None,
            help='Remove edge of given compound pairs from final graph ')
        parser.add_argument(
            '--split-map', action='store_true',
            help='Create dot file for reaction-splitted metabolic network visualization')
        super(VisualizationCommand, cls).init_parser(parser)

    def run(self):
        """Run visualization command."""

        # Mapping from compound id to formula
        compound_formula = {}
        for compound in self._model.compounds:
            if compound.formula is not None:
                try:
                    f = Formula.parse(compound.formula).flattened()
                    if not f.is_variable():
                        compound_formula[compound.id] = f
                    else:
                        logger.warning(
                            'Skipping variable formula {}: {}'.format(
                                compound.id, compound.formula))    #skip generic compounds
                except ParseError as e:
                    msg = (
                        'Error parsing formula'
                        ' for compound {}:\n{}\n{}'.format(
                            compound.id, e, compound.formula))
                    if e.indicator is not None:
                        msg += '\n{}'.format(e.indicator)
                    logger.warning(msg)

        # Mapping from string of cpd_id+compartment(eg: pyr_c[c]) to Compound object
        cpd_object = {}
        for cpd in self._mm.compounds:
            cpd_object[str(cpd)] = cpd

        # read exclude_compound_pairs from command-line argument
        exclude_cpairs = []
        if self._args.exclude_pairs is not None:
            for row in csv.reader(self._args.exclude_pairs, delimiter=str('\t')):
                exclude_cpairs.append((cpd_object[row[0]], cpd_object[row[1]]))
                exclude_cpairs.append((cpd_object[row[1]], cpd_object[row[0]]))

        # create {rxn_id:[(c1, c2),(c3,c4),...], ...} dictionary, key = rxn id, value = list of compound pairs
        filter_dict, split_reaction = make_filter_dict(self._model, self._mm, self._args.method, self._args.element,
                                                           compound_formula, cpd_object, exclude_cpairs,
                                                           self._args.exclude)

        # run l1min_fba, get reaction fluxes
        reaction_flux = {}
        if self._args.fba is True:
            solver = self._get_solver()
            p = fluxanalysis.FluxBalanceProblem(self._mm, solver)
            try:
                p.maximize(self._get_objective())
            except fluxanalysis.FluxBalanceError as e:
                self.report_flux_balance_error(e)

            fluxes = {r: p.get_flux(r) for r in self._mm.reactions}

            # Run flux minimization
            flux_var = p.get_flux_var(self._get_objective())
            p.prob.add_linear_constraints(flux_var == p.get_flux(self._get_objective()))
            p.minimize_l1()

            count = 0
            for r_id in self._mm.reactions:
                flux = p.get_flux(r_id)
                if abs(flux - fluxes[r_id]) > 1e-6:
                    count += 1
                if abs(flux) > 1e-6:
                    reaction_flux[r_id] = flux
            logger.info('Minimized reactions: {}'.format(count))

        # edge_values = make_edge_values(reaction_flux, self._mm, compound_formula, self._args.element,
        #                                self._args.split_map, cpairs_dict)


        # set of reactions to visualize
        if self._args.subset is not None:
            raw_subset, subset_reactions, mm_cpds = [], set(), []
            for line in self._args.subset.readlines():
                raw_subset.append(line.rstrip())
            for c in self._mm.compounds:
                mm_cpds.append(str(c))
            if set(raw_subset).issubset(set(self._mm.reactions)):
                subset_reactions = raw_subset
            elif set(raw_subset).issubset(set(mm_cpds)):
                for reaction in self._mm.reactions:
                    rx = self._mm.get_reaction(reaction)
                    if any(str(c) in raw_subset for (c, _) in rx.compounds):
                        subset_reactions.add(reaction)
            else:
                logger.warning('Invalid subset file. The file should contain a column of reaction id or a column '
                               'of compound id with compartment, mix of reactions, compounds and other infomation '
                               'in one subset file is not allowed. The function will generate entire metabolic '
                               'network of the model')
                subset_reactions = set(self._mm.reactions)
        else:
            subset_reactions = set(self._mm.reactions)
        #
        # def iter_reactions():
        #     """yield reactions that can applied to fpp"""
        #     for reaction in self._model.reactions:
        #         if (reaction.id not in self._model.model or
        #                 reaction.id in self._args.exclude):
        #             continue
        #
        #         if reaction.equation is None:
        #             logger.warning(
        #                 'Reaction {} has no reaction equation'.format(reaction.id))
        #             continue
        #
        #         if any(c.name not in compound_formula
        #                for c, _ in reaction.equation.compounds):
        #             logger.warning(
        #                 'Reaction {} has compounds with undefined formula'.format(reaction.id))
        #             continue
        #
        #         yield reaction

        # # read exclude_compound_pairs from command-line argument
        # exclude_cpairs = []
        # if self._args.exclude_pairs is not None:
        #     for row in csv.reader(self._args.exclude_pairs, delimiter=str('\t')):
        #         exclude_cpairs.append((cpd_object[row[0]], cpd_object[row[1]]))
        #         exclude_cpairs.append((cpd_object[row[1]], cpd_object[row[0]]))
        #
        # # create {rxn_id:[(c1, c2),(c3,c4),...], ...} dictionary, key = rxn id, value = list of compound pairs
        # filter_dict, split_reaction = make_filter_dict(self._model, self._mm, self._args.method, self._args.element,
        #                                                compound_formula,cpd_object, exclude_cpairs, self._args.exclude)

        # create {(c1, c2):[[forward rxns], [back rxns], [bidir rxns]], ...} dictionary, key=cpd_pair, value=rxn list
        raw_cpairs_dict = defaultdict(list)     # key=compound pair, value=list of reaction_id
        raw_dict = {k: v for k, v in iteritems(filter_dict) if k in subset_reactions}
        for rxn_id, cpairs in iteritems(raw_dict):
            for pair in cpairs:
                raw_cpairs_dict[pair].append(rxn_id)

        cpairs_dict = {}
        pair_list = []
        for (c1, c2), rxns in iteritems(raw_cpairs_dict):
            if (c1, c2) not in pair_list:
                forward_rxns, back_rxns, bidirectional_rxns = [], [], []
                for r in rxns:
                    reaction = self._mm.get_reaction(r)
                    if reaction.direction == Direction.Forward:
                        forward_rxns.append(r)
                    elif reaction.direction == Direction.Reverse:
                        back_rxns.append(r)
                    else:
                        if self._args.fba is True:
                            a = reaction_flux.get(r)
                            if a is not None:
                                if a > 0:
                                    forward_rxns.append(r)
                                else:
                                    back_rxns.append(r)
                            else:
                                bidirectional_rxns.append(r)
                        else:
                            bidirectional_rxns.append(r)

                if (c2, c1) in iterkeys(raw_cpairs_dict):
                    for r in raw_cpairs_dict[(c2, c1)]:
                        reaction = self._mm.get_reaction(r)
                        if reaction.direction == Direction.Forward:
                            back_rxns.append(r)
                        elif reaction.direction == Direction.Reverse:
                            forward_rxns.append(r)
                        else:
                            if self._args.fba is True:
                                a = reaction_flux.get(r)
                                if a is not None:
                                    if a > 0:
                                        back_rxns.append(r)
                                    else:
                                        forward_rxns.append(r)
                                else:
                                    bidirectional_rxns.append(r)
                            else:
                                bidirectional_rxns.append(r)
                cpair_rxn = namedtuple('cpair_rxn', ['forward', 'back', 'bidirection'])
                cpairs_dict[(c1, c2)] = cpair_rxn._make([forward_rxns, back_rxns, bidirectional_rxns])
            pair_list.append((c1, c2))
            pair_list.append((c2, c1))

        edge_values = make_edge_values(reaction_flux, self._mm, compound_formula, self._args.element,
                                       self._args.split_map, cpairs_dict)

        # if (cpd_object['gln_L_c[c]'], cpd_object['glu_L_c[c]']) in cpairs_dict:
        #     print((cpd_object['gln_L_c[c]'], cpd_object['glu_L_c[c]']),
        #           cpairs_dict[(cpd_object['gln_L_c[c]'], cpd_object['glu_L_c[c]'])])
        # else:
        #     print('false')
        #
        # for (c1, c2), v in iteritems(cpairs_dict):
        #     print(str(c1), str(c2), v)

        g, g1, g2 = self.create_bipartite_graph(self._mm, self._model, filter_dict, cpairs_dict,self._args.element,
                                                subset_reactions, edge_values,compound_formula, reaction_flux,
                                                split_graph=split_reaction)

        final_graph = None
        if self._args.method != 'no-fpp':
            if self._args.split_map is True:
                final_graph = g
            else:
                final_graph = g2
        else:
            if self._args.split_map is True:
                logger.warning('--split-map option can\'t be applied on visualization when method is no-fpp,'
                               ' break program')
                quit()
            else:
                final_graph = g

        with open('reactions.dot', 'w') as f:
            final_graph.write_graphviz(f)
        with open('reactions.nodes.tsv', 'w') as f:
            final_graph.write_cytoscape_nodes(f)
        with open('reactions.edges.tsv', 'w') as f:
            final_graph.write_cytoscape_edges(f)

        if self._args.Image is not None:
            if render is None:
                self.fail(
                    'create image file requires python binding graphviz module'
                    ' ("pip install graphviz")')
            else:
                if len(subset_reactions) > 500:
                    logger.info(
                        'The program is going to create a large graph that contains {} reactions, '
                        'it may take a long time'.format(len(subset_reactions)))
                try:
                    render('dot', self._args.Image, 'reactions.dot')
                except subprocess.CalledProcessError:
                    logger.warning('the graph is too large to create')


    def create_bipartite_graph(self, model, nativemodel, predict_results, cpair_dict, element, subset,
                                     edge_values, cpd_formula, reaction_flux, split_graph=True):
        """create bipartite graph of given metabolic network

        Start from a dictionary comprises compound pairs and related reaction ids, Returns a Graph object
        that contains a set of nodes and a dictionary of edges, node and edge properties(such as node color, shape and
        edge direction) are included.

        Args:
        model: class 'psamm.metabolicmodel.MetabolicModel'.
        nativemodel: class 'psamm.datasource.native.NativeModel'.
        predict_results: Dictionary mapping reaction IDs to compound pairs(reactant/product pair that transfers
            specific element,by default the ekement is carbon(C).
        cpair_dict: Dictionary mapping compound pair to a list of reaction IDs.
        element: a string that represent a specific chemical element, such as C(carbon), S(sulfur), N(nitrogen).
        subset: Set of reactions for visualizing.
        edge_values: Dictionary mapping (reaction ID, compound ID) to values of edge between them.
        cpd_formula: Dictionary mapping compound IDs to
            :class:`psamm.formula.Formula`. Formulas must be flattened.
        reaction_flux: Dictionary mapping reaction ID to reaction flux. Flux is a float number.
        split_graph: An argument used to decide if split node for one reaction. Default is 'True'"""

        g = graph.Graph()
        g1 = graph.Graph()
        g2 = graph.Graph()
        g3 = graph.Graph()

        # Mapping from compound id to DictCompoundEntry object
        cpd_entry = {}
        for cpd in nativemodel.compounds:
            cpd_entry[cpd.id] = cpd

        # Mapping from reaction id to DictReactionEntry object
        rxn_entry = {}
        for rxn in nativemodel.reactions:
            rxn_entry[rxn.id] = rxn

        # setting node color
        recolor_dict = {}
        if self._args.color is not None:
            for f in self._args.color:
                for row in csv.reader(f, delimiter=str(u'\t')):
                    recolor_dict[row[0]] = row[1]  # row[0] =reaction id or str(cpd object), row[1] = hex color code
        color = {}
        for c in model.compounds:
            if str(c) in recolor_dict:
                color[c] = recolor_dict[str(c)]
            else:
                color[c] = COMPOUND_COLOR
        for r in model.reactions:
            if r in recolor_dict:
                color[r] = recolor_dict[r]
            else:
                color[r] = REACTION_COLOR

        # define reaction node color for rxns-combined graph
        def final_rxn_color(color_args, rlist):
            if color_args is not None:
                if len(rlist) == 1:
                    return color[rlist[0]]
                else:
                    if any(r in recolor_dict for r in rlist):
                        return RXN_COMBINED_COLOR
                    else:
                        return REACTION_COLOR
            else:
                return REACTION_COLOR

        # preparing for scaling width of edges
        if len(edge_values) > 0:
            value_list = sorted(edge_values.values())
            ninty_percentile = value_list[int(len(value_list)*0.9)+1]
            min_edge_value = min(itervalues(edge_values))
            max_edge_value = ninty_percentile
        else:
            min_edge_value = 1
            max_edge_value = 1

        def pen_width(value):
            """calculate final edges width"""
            if max_edge_value - min_edge_value == 0:
                return 1
            else:
                if value > max_edge_value:
                    value = max_edge_value
                alpha = value / max_edge_value

                return 10 * alpha

        def dir_value(direction):
            """assign value to different reaction directions"""
            if direction == Direction.Forward:
                return 'forward'
            elif direction == Direction.Reverse:
                return 'back'
            else:
                return 'both'

        def final_props(reaction, edge1, edge2):
            """set final properties of edges"""
            if len(edge_values) > 0:
                p = {}
                if edge1 in edge_values:
                    p['dir'] = 'forward'
                    p['penwidth'] = pen_width(edge_values[edge1])
                elif edge2 in edge_values:
                    p['dir'] = 'back'
                    p['penwidth'] = pen_width(edge_values[edge2])
                else:
                    p['style'] = 'dotted'
                    p['dir'] = dir_value(reaction.direction)
                return p
            else:
                return {'dir': dir_value(reaction.direction)}

        # create standard bipartite graph
        cpds = []  # cpds in predict_results
        rxns = Counter()
        compound_nodes = {}
        edge_list = []
        for rxn_id, cpairs in sorted(iteritems(predict_results)):
            if rxn_id in subset:
                for (c1, c2) in cpairs:
                    if c1 not in cpds:          # c1.name = compound.id, no compartment
                        node = graph.Node({
                            'id': text_type(c1),
                            'edge_id': text_type(c1),
                            'label': cpds_properties(c1, cpd_entry[c1.name], self._args.detail),
                            'shape': 'ellipse',
                            'style': 'filled',
                            'fillcolor': color[c1]})
                        g.add_node(node)
                        g1.add_node(node)
                        compound_nodes[c1] = node
                    if c2 not in cpds:
                        node = graph.Node({
                            'id': text_type(c2),
                            'edge_id': text_type(c2),
                            'label': cpds_properties(c2, cpd_entry[c2.name], self._args.detail),
                            'shape': 'ellipse',
                            'style': 'filled',
                            'fillcolor': color[c2]})
                        g.add_node(node)
                        g1.add_node(node)
                        compound_nodes[c2] = node
                    cpds.append(c1)
                    cpds.append(c2)

                    if split_graph is True:
                        rxns[rxn_id] += 1
                        node_id = '{}_{}'.format(rxn_id, rxns[rxn_id])
                    else:
                        node_id = rxn_id
                    node = graph.Node({
                        'id': node_id,
                        'edge_id': rxn_id,
                        'label': rxns_properties(rxn_entry[rxn_id], self._args.detail, reaction_flux),
                        'shape': 'box',
                        'style': 'filled',
                        'fillcolor': color[rxn_id]})
                    g.add_node(node)

                    rx = model.get_reaction(rxn_id)

                    edge1 = c1, rxn_id  # forward
                    edge2 = rxn_id, c1
                    if split_graph is True:
                        g.add_edge(graph.Edge(
                            compound_nodes[c1], node, final_props(rx, edge1, edge2)))
                    else:
                        if edge1 and edge2 not in edge_list:
                            edge_list.append(edge1)
                            edge_list.append(edge2)
                        g.add_edge(graph.Edge(
                            compound_nodes[c1], node, final_props(rx, edge1, edge2)))

                    edge1 = rxn_id, c2 # forward
                    edge2 = c2, rxn_id
                    if split_graph is True:
                        g.add_edge(graph.Edge(
                            node, compound_nodes[c2], final_props(rx, edge1, edge2)))
                    else:
                        if edge1 and edge2 not in edge_list:
                            edge_list.append(edge1)
                            edge_list.append(edge2)
                        g.add_edge(graph.Edge(
                            node, compound_nodes[c2], final_props(rx, edge1, edge2)))

                    g1.add_edge(graph.Edge(
                        compound_nodes[c1], compound_nodes[c2], {'dir': dir_value(rx.direction), 'reaction': rxn_id}))

        # create bipartite and reactions-combined graph if --method is fpp

        def condensed_rxn_props(detail, r_list, reaction_flux):
            if len(r_list) == 1:
                label_comb = rxns_properties(rxn_entry[r_list[0]], detail, reaction_flux)
            else:
                if len(reaction_flux) > 0:
                    sum_flux = 0
                    for r in r_list:
                        if r in reaction_flux:
                            sum_flux += abs(reaction_flux[r])
                    label_rxns = '\n'.join(r for r in r_list)
                    label_comb = '{}\n{}'.format(label_rxns, sum_flux)
                else:
                    label_comb = '\n'.join(r for r in r_list)
            return label_comb

        def dir_value_2(r_list):
            if r_list == rxns.forward:
                return {'dir': 'forward'}
            elif r_list == rxns.back:
                return {'dir': 'back'}
            else:
                return {'dir': 'both'}

        def final_props_2(rlist, edge1, edge2):
            if len(edge_values) > 0:
                p = {}
                if edge1 in edge_values:
                    p['penwidth'] = pen_width(edge_values[edge1])
                elif edge2 in edge_values:
                    p['penwidth'] = pen_width(edge_values[edge2])
                else:
                    p['style'] = 'dotted'

                p['dir'] = dir_value_2(rlist)['dir']

                return p
            else:
                return dir_value_2(rlist)

        # create compound nodes and add nodes to Graph object
        compound_set = set()
        for (c1, c2), rxns in iteritems(cpair_dict):
            compound_set.add(c1)
            compound_set.add(c2)
        cpd_nodes = {}
        for cpd in compound_set:    # cpd=compound object, cpd.name=compound id, no compartment
            node = graph.Node({
                'id': text_type(cpd),
                'label': cpds_properties(cpd, cpd_entry[cpd.name], self._args.detail),
                'shape': 'ellipse',
                'style': 'filled',
                'fillcolor': color[cpd]})
            cpd_nodes[cpd] = node
            g2.add_node(node)
            g3.add_node(node)       # g3=new split map

        # create and add reaction nodes, add edges
        cpd_pairs = Counter()
        for (c1, c2), rxns in iteritems(cpair_dict):
            for r_list in rxns:
                if len(r_list) > 0:
                    cpd_pairs[(c1, c2)] += 1
                    node = graph.Node({
                        'id': '{}_{}'.format((str(c1), str(c2)), cpd_pairs[(c1, c2)]),
                        'label': condensed_rxn_props(self._args.detail, r_list, reaction_flux),
                        'shape': 'box',
                        'style': 'filled',
                        'fillcolor': final_rxn_color(self._args.color, r_list)})
                    g2.add_node(node)

                    if len(r_list) == 1:
                        reac = r_list[0]        # a single rxn id
                    else:
                        reac = tuple(r_list)    # a list of rxn id

                    edge1 = c1, reac
                    edge2 = reac, c1
                    g2.add_edge(graph.Edge(
                        cpd_nodes[c1], node, final_props_2(r_list, edge1, edge2)))

                    edge1 = reac, c2
                    edge2 = c2, reac
                    g2.add_edge(graph.Edge(
                        node, cpd_nodes[c2], final_props_2(r_list, edge1, edge2)))

        # add exchange reaction nodes
        rxn_set = set()
        for reaction in subset:
            if model.is_exchange(reaction):
                raw_exchange_rxn = model.get_reaction(reaction)
                if element is not None:
                    if any(Atom(primary_element(element)) in cpd_formula[str(c[0].name)]
                           for c in raw_exchange_rxn.compounds):
                            rxn_set.add(reaction)
                else:
                    rxn_set.add(reaction)
        for r in rxn_set:
            exchange_rxn = model.get_reaction(r)
            label = r
            if len(edge_values) > 0:
                if r in iterkeys(edge_values):
                    label = '{}\n{}'.format(r, edge_values[r])
            node_ex = graph.Node({
                'id': r,
                'edge_id': r,
                'label': label,
                'shape': 'box',
                'style': 'filled',
                'fillcolor': ACTIVE_COLOR})
            g.add_node(node_ex)
            g2.add_node(node_ex)

            for c1, _ in exchange_rxn.left:
                if c1 not in compound_nodes.keys():
                    node_ex_cpd = graph.Node({
                        'id': text_type(c1),
                        'edge_id':text_type(c1),
                        'label': cpds_properties(c1, cpd_entry[c1.name], self._args.detail),
                        'shape': 'ellipse',
                        'style': 'filled',
                        'fillcolor': CPD_ONLY_IN_EXC})
                    g.add_node(node_ex_cpd)
                    compound_nodes[c1] = node_ex_cpd

                    g2.add_node(node_ex_cpd)
                    cpd_nodes[c1] = node_ex_cpd

                edge1 = c1, r
                edge2 = r, c1
                g.add_edge(graph.Edge(
                    compound_nodes[c1], node_ex, final_props(exchange_rxn, edge1, edge2)))
                g2.add_edge(graph.Edge(
                    cpd_nodes[c1], node_ex, final_props(exchange_rxn, edge1, edge2)))

            for c2, _ in exchange_rxn.right:
                if c2 not in compound_nodes.keys():
                    node_ex_cpd = graph.Node({
                        'id': text_type(c2),
                        'edge_id': text_type(c2),
                        'label': cpds_properties(c2, cpd_entry[c2.name], self._args.detail),
                        'shape': 'ellipse',
                        'style': 'filled',
                        'fillcolor': CPD_ONLY_IN_EXC})
                    g.add_node(node_ex_cpd)
                    compound_nodes[c2] = node_ex_cpd

                    g2.add_node(node_ex_cpd)
                    cpd_nodes[c2] = node_ex_cpd

                edge1 = r, c2
                edge2 = c2, r
                g.add_edge(graph.Edge(
                    node_ex, compound_nodes[c2], final_props(exchange_rxn, edge1, edge2)))
                g2.add_edge(graph.Edge(
                    node_ex, cpd_nodes[c2], final_props(exchange_rxn, edge1, edge2)))

        # add biomass reaction nodes
        bio_pair = Counter()
        biomass_cpds = set()
        if nativemodel.biomass_reaction is not None:
            if nativemodel.biomass_reaction in subset:
                biomass_reaction = model.get_reaction(nativemodel.biomass_reaction)
                for c, _ in biomass_reaction.left:
                    if element is not None:
                        if Atom(primary_element(element)) in cpd_formula[str(c.name)]:
                            biomass_cpds.add(c)
                    else:
                        biomass_cpds.add(c)
                for c in biomass_cpds:
                    bio_pair[nativemodel.biomass_reaction] += 1
                    # bio_pair = Counter({'biomass_rxn_id': 1}), Counter({'biomass_rxn_id': 2})...
                    node_bio = graph.Node({
                        'id': '{}_{}'.format(nativemodel.biomass_reaction, bio_pair[nativemodel.biomass_reaction]),
                        'edge_id': nativemodel.biomass_reaction,
                        'label': nativemodel.biomass_reaction,
                        'shape': 'box',
                        'style': 'filled',
                        'fillcolor': ALT_COLOR})
                    g.add_node(node_bio)
                    g2.add_node(node_bio)

                    if c not in compound_nodes.keys():
                        node_bio_cpd = graph.Node({
                            'id': text_type(c),
                            'edge_id': text_type(c),
                            'label': cpds_properties(c, cpd_entry[c.name], self._args.detail),
                            'shape': 'ellipse',
                            'style': 'filled',
                            'fillcolor': CPD_ONLY_IN_BIO})
                        g.add_node(node_bio_cpd)
                        compound_nodes[c] = node_bio_cpd

                        g2.add_node(node_bio_cpd)
                        cpd_nodes[c] = node_bio_cpd

                    edge1 = c, nativemodel.biomass_reaction
                    edge2 = nativemodel.biomass_reaction, c
                    g.add_edge(graph.Edge(
                        compound_nodes[c], node_bio, final_props(biomass_reaction, edge1, edge2)))
                    g2.add_edge(graph.Edge(
                        cpd_nodes[c], node_bio, final_props(biomass_reaction, edge1, edge2)))
        else:
            logger.warning(
                'No biomass reaction in this model')

        return g, g1, g2