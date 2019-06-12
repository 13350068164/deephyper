"""Asynchronous Model-Based Search.

Arguments of AMBS :
* ``learner``

    * ``RF`` : Random Forest (default)
    * ``ET`` : Extra Trees
    * ``GBRT`` : Gradient Boosting Regression Trees
    * ``DUMMY`` :
    * ``GP`` : Gaussian process

* ``liar-strategy``

    * ``cl_max`` : (default)
    * ``cl_min`` :
    * ``cl_mean`` :

* ``acq-func`` : Acquisition function

    * ``LCB`` :
    * ``EI`` :
    * ``PI`` :
    * ``gp_hedge`` : (default)
"""


import signal
import json

from deephyper.search.nas.optimizer import Optimizer
from deephyper.search import Search
from deephyper.search import util

logger = util.conf_logger('deephyper.search.nas.ambs')

SERVICE_PERIOD = 2          # Delay (seconds) between main loop iterations
CHECKPOINT_INTERVAL = 1    # How many jobs to complete between optimizer checkpoints
EXIT_FLAG = False


def on_exit(signum, stack):
    global EXIT_FLAG
    EXIT_FLAG = True


def key(d):
    return json.dumps(dict(arch_seq=d['arch_seq']))


class AMBNeuralArchitectureSearch(Search):
    def __init__(self, problem, run, evaluator, cache_key=key, **kwargs):
        super().__init__(problem, run, evaluator, **kwargs)
        logger.info("Initializing AMBS")
        self.optimizer = Optimizer(self.problem, self.num_workers, self.args)

    @staticmethod
    def _extend_parser(parser):
        parser.add_argument("--problem",
                            type=str,
                            default="deephyper.benchmark.nas.linearReg.Problem",
                            help="Module path to the Problem instance you want to use for the search (e.g. deephyper.benchmark.nas.linearReg.Problem)."
                            )
        parser.add_argument("--run",
                            type=str,
                            default="deephyper.search.nas.model.run.quick",
                            help="Module path to the run function you want to use for the search (e.g. deephyper.search.nas.model.run.quick)."
                            )
        parser.add_argument('--max-evals',
                            type=int,
                            default=1e10,
                            help='maximum number of evaluations.')
        parser.add_argument('--learner',
                            default='RF',
                            choices=["RF", "ET", "GBRT", "DUMMY", "GP"],
                            help='type of learner (surrogate model)'
                            )
        parser.add_argument('--liar-strategy',
                            default="cl_max",
                            choices=["cl_min", "cl_mean", "cl_max"],
                            help='Constant liar strategy'
                            )
        parser.add_argument('--acq-func',
                            default="gp_hedge",
                            choices=["LCB", "EI", "PI", "gp_hedge"],
                            help='Acquisition function type'
                            )
        return parser

    def main(self):
        timer = util.DelayTimer(max_minutes=None, period=SERVICE_PERIOD)
        chkpoint_counter = 0
        num_evals = 0

        logger.info(f"Generating {self.num_workers} initial points...")
        XX = self.optimizer.ask_initial(n_points=self.num_workers)
        self.evaluator.add_eval_batch(XX)

        # MAIN LOOP
        for elapsed_str in timer:
            logger.info(f"Elapsed time: {elapsed_str}")
            results = list(self.evaluator.get_finished_evals())
            num_evals += len(results)
            chkpoint_counter += len(results)
            if EXIT_FLAG or num_evals >= self.args.max_evals:
                break
            if results:
                logger.info(
                    f"Refitting model with batch of {len(results)} evals")
                self.optimizer.tell(results)
                logger.info(
                    f"Drawing {len(results)} points with strategy {self.optimizer.strategy}")
                # ! 'ask' is written as a generator because asking for a large batch is
                # ! slow. We get better performance when ask is batched. The RF is
                # ! constantly re-fitting during the call to ask. So it becomes slow
                # ! when there are a large number of workers.
                for batch in self.optimizer.ask(n_points=len(results)):
                    self.evaluator.add_eval_batch(batch)
            if chkpoint_counter >= CHECKPOINT_INTERVAL:
                self.evaluator.dump_evals()
                chkpoint_counter = 0

        logger.info('Hyperopt driver finishing')
        self.evaluator.dump_evals(saved_key='arch_seq')


if __name__ == "__main__":
    args = AMBNeuralArchitectureSearch.parse_args()
    search = AMBNeuralArchitectureSearch(**vars(args))
    signal.signal(signal.SIGINT, on_exit)
    signal.signal(signal.SIGTERM, on_exit)
    search.main()
