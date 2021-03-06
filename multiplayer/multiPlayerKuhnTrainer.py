from random import shuffle
from multiplayer import kuhnHelper
import numpy as np
from io import StringIO
from csv import writer

# Aggressive - B
B = 'BET'
C = 'CALL'

# Non-Aggressive - P
K = 'CHECK'
F = 'FOLD'


class TrainerInfoSet:
    # Information set node class definition
    NUM_ACTIONS = 2

    def __init__(self, info_set='', gen_graphs=False):
        # Kuhn Node Definitions
        self.info_set = info_set
        self.regret_sum = [0] * self.NUM_ACTIONS
        self.strategy_sum = [0] * self.NUM_ACTIONS
        self.gen_graphs = gen_graphs

        self.strat_output = StringIO()
        self.strat_csv_writer = writer(self.strat_output)

        self.regret_output = StringIO()
        self.regret_csv_writer = writer(self.regret_output)

    def get_strategy(self, realization_weight):
        """
        Get current information set mixed strategy through regret matching
        :param realization_weight:
        :return:
        """
        normalizing_sum = 0.0
        strategy = [0.0] * self.NUM_ACTIONS
        for i in range(0, self.NUM_ACTIONS):
            strategy[i] = self.regret_sum[i] if self.regret_sum[i] > 0 else 0.0
            normalizing_sum += strategy[i]

        for i in range(0, self.NUM_ACTIONS):
            if normalizing_sum > 0:
                strategy[i] /= normalizing_sum
            else:
                strategy[i] = 1.0 / self.NUM_ACTIONS

            self.strategy_sum[i] += realization_weight * strategy[i]

        if self.gen_graphs:
            avg_strat = self.get_average_strategy()
            self.strat_csv_writer.writerow(avg_strat)

        return strategy

    def get_average_strategy(self):
        """
        Get average information set mixed strategy across all training iterations
        :return:
        """
        avg_strategy = [0] * self.NUM_ACTIONS
        normalizing_sum = 0.0
        for i in range(0, self.NUM_ACTIONS):
            normalizing_sum += self.strategy_sum[i]

        for i in range(0, self.NUM_ACTIONS):
            if normalizing_sum > 0:
                avg_strategy[i] = self.strategy_sum[i] / normalizing_sum
            else:
                avg_strategy[i] = 1.0 / self.NUM_ACTIONS

        return avg_strategy

    def to_string(self):
        # TODO: remove?
        # Get info set string representation
        avg_strat = self.get_average_strategy()
        print('info_set is: {0} and average strategy for BET: {1.4f} PASS: {2:.4f}'.format(self.info_set, avg_strat[0], avg_strat[1]))


class KuhnTrainer:
    # Kuhn Poker Definitions
    PASS = 0
    BEST = 1
    NUM_ACTIONS = 2
    NUM_PLAYERS = 3

    def __init__(self, training_best_response=False, best_response_player=None, strategy_profile=None, generate_graphs=False, base_dir=None):
        self.training_best_response = training_best_response
        self.best_response_player = best_response_player
        self.strategy_profile = strategy_profile
        self.node_map = {}
        self.gen_graphs = generate_graphs
        self.base_dir = base_dir

    def cfr(self, cards, history, reach_probabilities):
        """
        Counterfactual regret minimization for Kuhn Poker
        :param cards:   list[int] -
        :param history: string    -
        :param reach_probabilities: list [ float ] - probability of action for players 1, 2, 3
        :param
        :return: terminal_utilities: dict {str: list[int]}
        """
        plays = len(history)
        current_player = plays % 3
        rp0, rp1, rp2 = reach_probabilities
        util = [0.0] * self.NUM_ACTIONS
        terminal_utilities = np.zeros(self.NUM_PLAYERS)

        if kuhnHelper.is_terminal_state(plays, history):
            # Terminal Utility is pre-defined for each player based on the current state
            utility = kuhnHelper.calculate_terminal_payoff(history, cards)
            return utility

        # Get information set node or create it if has not been visited yet
        info_set = str(cards[current_player]) + history
        if info_set in self.node_map:
            info_set_node = self.node_map[info_set]
        else:
            info_set_node = TrainerInfoSet(info_set, self.gen_graphs)
            self.node_map[info_set] = info_set_node

        # Best Response Strategies for opponents are pre-defined and provided to the class.
        if self.training_best_response and self.best_response_player != current_player:
            strategy = self.strategy_profile[info_set]
        else:
            # Get updated strategy based on cumulative regret
            strategy = info_set_node.get_strategy(reach_probabilities[current_player])

        for a in range(0, self.NUM_ACTIONS):
            # For each action, recursively call cfr with additional history and probability
            next_history = history + ('p' if a == 0 else 'b')
            if current_player == 0:
                child_utilities = self.cfr(cards, next_history, [rp0 * strategy[a], rp1, rp2])
            elif current_player == 1:
                child_utilities = self.cfr(cards, next_history, [rp0, rp1 * strategy[a], rp2])
            else:  # Player 2
                child_utilities = self.cfr(cards, next_history, [rp0, rp1, rp2 * strategy[a]])

            # Calculating CFR for the current infoset
            util[a] = child_utilities[current_player]

            # Used to pass up to parent infoset
            weighted_utilities = [strategy[a] * z for z in child_utilities]
            terminal_utilities = np.add(terminal_utilities, weighted_utilities)

        node_util = terminal_utilities[current_player]

        # For each action, compute and accumulate counterfactual regret
        for i in range(0, self.NUM_ACTIONS):
            regret = util[i] - node_util
            # CFR is multiplied by reach probability (from previous player) of getting to the current state
            if current_player == 0:
                info_set_node.regret_sum[i] += rp2 * regret
            elif current_player == 1:
                info_set_node.regret_sum[i] += rp0 * regret
            else:
                info_set_node.regret_sum[i] += rp1 * regret

        if self.gen_graphs:
            r = info_set_node.regret_sum.copy()
            info_set_node.regret_csv_writer.writerow(r)

        return terminal_utilities

    def _return_player_strats(self, strategy_profile):
        # Player 1, 2, and 3's betting strategies
        p1, p2, p3 = kuhnHelper.get_positions_from_strategy_profile(strategy_profile)

        if self.best_response_player == 0:
            return p1
        elif self.best_response_player == 1:
            return p2
        elif self.best_response_player == 2:
            return p3
        else:
            # No best response player, so training CFR for all players
            return strategy_profile

    def train(self, iterations):
        """
        Train Kuhn Poker
        :param iterations:
        :return:
        """
        strategy_profile = {}
        cards = [1, 2, 3, 4]
        util = 0
        for _ in range(iterations):
            shuffle(cards)
            util += self.cfr(cards, '', [1, 1, 1])

        print('Average game value: {}'.format(util / iterations))
        for info_set in sorted(self.node_map):
            node = self.node_map[info_set]
            avg_strat = node.get_average_strategy()
            strategy_profile[info_set] = [avg_strat[0], avg_strat[1]]

        if self.gen_graphs:
            # For large iterations use _save_training to export data into csv
            #kuhnHelper._save_training_data(self.node_map, self.base_dir)
            kuhnHelper.plot_strat_and_regret(self.node_map, self.base_dir)

        return self._return_player_strats(strategy_profile)
