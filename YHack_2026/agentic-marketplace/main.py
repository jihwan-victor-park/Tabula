"""Entry point — runs the full overnight coordination cycle and writes JSON output."""

import argparse
import sys
from coordination.overnight_pipeline import OvernightPipeline
from utils.logger import Logger
import config


def main():
    parser = argparse.ArgumentParser(description="Run the agentic marketplace overnight cycle")
    parser.add_argument(
        "--scenario",
        choices=list(config.SCENARIOS.keys()),
        default="default",
        help="Market scenario to simulate",
    )
    parser.add_argument("--verbose", action="store_true", help="Log full API transcripts")
    parser.add_argument("--chat", action="store_true", help="Generate group chat simulation")
    args = parser.parse_args()

    try:
        pipeline = OvernightPipeline(
            scenario=args.scenario,
            verbose=args.verbose,
            chat_mode=args.chat,
        )
        results = pipeline.run()

        Logger.header("Cycle Complete")
        Logger.info(f"Cycle ID: {results.cycle_id}")
        Logger.info(f"Trends: {len(results.market_trends)}")
        Logger.info(f"Stores: {len(results.store_results)}")
        if results.verification:
            Logger.info(f"Solana verification: {results.verification.get('signal_count', 0)} signals on-chain")
            Logger.info(f"Summary on-chain: {results.verification.get('summary_on_chain', False)}")

        # Also generate the compact debate summary
        from generate_summary import generate_summary
        generate_summary()

    except Exception as e:
        Logger.error(f"Pipeline failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
