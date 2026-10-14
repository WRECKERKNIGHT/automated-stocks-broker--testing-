"""Trading & investing knowledge base.

A curated library of ~100 of the most influential trading / investing / market
books, each distilled to its core lessons. It powers:

  * the "library" browser in the dashboard,
  * the "coach" - a rule-based advisor that surfaces the principles most
    relevant to the current market / portfolio situation,
  * an optional context block for the LLM analyst so its narrative is grounded
    in well-known trading wisdom.

This is deliberately *educational* material (distilled, attributed principles),
not verbatim text from the books. Use it as a checklist, not gospel.
"""
from __future__ import annotations

import random
import time
from typing import Any

# ------------------------------------------------------------------ categories
RISK = "Risk & Money Management"
PSYCH = "Psychology & Discipline"
TECH = "Technical Analysis & Charting"
SYSTEM = "Systems, Strategy & Edge"
MICRO = "Market Structure & Order Flow"
TREND = "Trend & Momentum"
VALUE = "Value & Fundamentals"
HISTORY = "Market History & Bubbles"
SPEC = "Speculation & Mindset"
QUANT = "Quant, Stats & Machine Learning"
OPTIONS = "Options & Derivatives"
PROB = "Probability & Decision Making"
CATEGORIES = [RISK, PSYCH, TECH, SYSTEM, MICRO, TREND, VALUE, HISTORY, SPEC, QUANT, OPTIONS, PROB]


def _b(title: str, author: str, year: int, category: str, lessons: list[str]) -> dict:
    return {"title": title, "author": author, "year": year, "category": category, "lessons": lessons}


BOOKS: list[dict] = [
    _b("Reminiscences of a Stock Operator", "Edwin Lefevre", 1923, SPEC, [
        "There is nothing new in speculation - the same patterns and human emotions repeat forever.",
        "The big money is not in the buying and selling but in the waiting.",
        "Never average down on a losing position; the market is telling you that you are wrong.",
        "Cut your losses quickly; let your winners run.",
        "Trade the market's reaction to the news, not the news itself.",
        "A man must believe in himself and trust his own judgement to make money trading.",
    ]),
    _b("How I Made $2,000,000 in the Stock Market", "Nicolas Darvas", 1960, SPEC, [
        "Ride winners with a trailing stop; remove your ego from the exit decision.",
        "Buy strength into new highs, not weakness - momentum begets momentum.",
        "Set your stop the moment you enter, before emotion clouds the decision.",
        "Write your plan down; discipline beats improvisation.",
    ]),
    _b("Market Wizards", "Jack Schwager", 1989, SYSTEM, [
        "Every great trader has a personal, disciplined method - not a magic indicator.",
        "Risk control, not prediction, is what separates survivors from casualties.",
        "Losses are the cost of doing business; keep them small and expected.",
        "The market rewards flexibility and punishes stubbornness.",
        "Find what works for your temperament, then repeat it relentlessly.",
    ]),
    _b("The New Market Wizards", "Jack Schwager", 1992, SYSTEM, [
        "Process over outcome: good trades can lose, bad trades can win - judge the process.",
        "Diversify across uncorrelated methods and markets to smooth equity.",
        "Know your edge precisely and only trade when it is present.",
        "Survive first; profits follow the survivors.",
    ]),
    _b("Hedge Fund Market Wizards", "Jack Schwager", 2012, SYSTEM, [
        "Great managers size positions by conviction and volatility together.",
        "Avoid over-diversification that dilutes your true edge.",
        "Understand the macro regime you operate in before sizing up.",
        "The best risk management is avoiding crowded, fragile trades.",
    ]),
    _b("Trading in the Zone", "Mark Douglas", 2000, PSYCH, [
        "The market is neutral; your pain comes from your unmet expectations.",
        "Think in probabilities - a series of trades as one continuous distribution.",
        "Predefine your risk so no single outcome can provoke fear or revenge.",
        "You do not need to know what happens next to make money.",
        "Consistency comes from a disciplined mind, not a perfect method.",
    ]),
    _b("The Disciplined Trader", "Mark Douglas", 1990, PSYCH, [
        "Trading success is 80% psychology and 20% method.",
        "Act as an observer of the market, free of the need to be right.",
        "Rules eliminate the emotional decision points where losses originate.",
        "Accept that you cannot control the market, only your own responses.",
    ]),
    _b("The New Trading for a Living", "Alexander Elder", 2014, SYSTEM, [
        "Use the 'three M's': Mind, Method, Money.",
        "The 2% and 6% rules: risk no more than 2% per trade and 6% per month.",
        "Trade with the trend and use multiple timeframes for confirmation.",
        "Keep a trading diary; unexamined trades repeat their mistakes.",
    ]),
    _b("Come Into My Trading Room", "Alexander Elder", 2002, SYSTEM, [
        "Amateurs ask where the market is going; professionals manage risk.",
        "A (method) + B (money management) + C (psychology) - all three are required.",
        "Record every trade with a screenshot and a grade.",
    ]),
    _b("Technical Analysis of the Financial Markets", "John Murphy", 1999, TECH, [
        "Price discounts everything; the chart is a proxy for all known information.",
        "History rhymes - patterns and support/resistance repeat because behaviour repeats.",
        "Use multiple indicators across trend, momentum and volatility - never one alone.",
        "Volume confirms price; divergence warns of weak moves.",
    ]),
    _b("Japanese Candlestick Charting Techniques", "Steve Nison", 1991, TECH, [
        "Candlesticks reveal the tug-of-war between buyers and sellers.",
        "Reversal patterns matter most at support or resistance, not in a vacuum.",
        "Confirm every candle pattern with the surrounding trend and volume.",
    ]),
    _b("The Art and Science of Technical Analysis", "Adam Grimes", 2012, TECH, [
        "Markets cycle through trends and ranges; use the right tool for each.",
        "Edges are small and probabilistic - you must trade them many times.",
        "Support/resistance is a process of failed auction, not a line.",
        "Losses and drawdowns are part of the statistical edge, not anomalies.",
    ]),
    _b("Trading Price Action: Trends", "Al Brooks", 2012, TECH, [
        "Every move is a breakout, a channel, or a trading range.",
        "Trade with the trend; take the first pullback to the moving average.",
        "Read bar by bar: context and prior bars define the probability of the next.",
        "When unsure, wait - most setups are traps within ranges.",
    ]),
    _b("Reading Price Charts Bar by Bar", "Al Brooks", 2009, TECH, [
        "The best trades come from failed attempts at the obvious.",
        "A strong trend bar signals continuation, not exhaustion.",
    ]),
    _b("Secrets of a Pivot Boss", "Franklin Ochoa", 2010, TECH, [
        "Pivots, value areas and profile levels anchor institutional interest.",
        "Trade the reaction to key levels, not the levels themselves.",
    ]),
    _b("Trade Like a Stock Market Wizard", "Mark Minervini", 2013, TREND, [
        "The best stocks show a consistent, volatility-contracted uptrend (VCP).",
        "Buy at the pivot on a breakout with expanding volume.",
        "Protect capital with tight stops; find the best setup, then the entry.",
        "Relative strength and earnings acceleration identify future leaders.",
    ]),
    _b("Think & Trade Like a Champion", "Mark Minervini", 2017, TREND, [
        "Develop your own risk-first trading plan and follow it every day.",
        "Losers average losers; winners add to winners.",
        "Be a sniper, not a machine gunner - wait for the elite setup.",
    ]),
    _b("Trend Following", "Michael Covel", 2004, TREND, [
        "A few large winners pay for many small losers - structure ensures survival.",
        "Trend followers do not predict; they react to price with rules.",
        "Diversify across markets; trends appear somewhere most of the time.",
    ]),
    _b("The Complete TurtleTrader", "Michael Covel", 2007, SYSTEM, [
        "A simple rules-based system, applied with discipline, beats intuition.",
        "Position sizing and diversification are the true secrets.",
        "Breakouts with volatility-based stops form a robust trend system.",
    ]),
    _b("Way of the Turtle", "Curtis Faith", 2007, SYSTEM, [
        "The edge is in position sizing and risk, not entry magic.",
        "Expect long losing streaks; size so they cannot ruin you.",
        "Fees and slippage are real costs - favour liquid markets.",
    ]),
    _b("Following the Trend", "Andreas Clenow", 2013, TREND, [
        "Diversified trend following across many futures is robust and simple.",
        "Volatility-based position sizing equalises risk across markets.",
        "Long flat periods are normal; patience is the edge.",
    ]),
    _b("Trade Your Way to Financial Freedom", "Van Tharp", 1998, RISK, [
        "Position sizing is the single most important determinant of returns.",
        "You do not trade markets, you trade your beliefs about markets.",
        "Expectancy = win rate x avg win - loss rate x avg loss; it must be positive.",
        "Let profits run only within a tested system; define 'R' multiples up front.",
    ]),
    _b("Definitive Guide to Position Sizing", "Van Tharp", 2008, RISK, [
        "Risk a fixed, small fraction of equity per trade (0.5-1%).",
        "Size for the worst plausible loss, not the average one.",
        "Reducing bet size during drawdowns preserves capital to recover.",
    ]),
    _b("The Most Important Thing", "Howard Marks", 2011, RISK, [
        "Risk means more things can happen than will happen - respect the tails.",
        "Buy with a margin of safety; price paid determines the return.",
        "You cannot predict, but you can prepare; be a contrarian of discipline.",
        "Avoiding losers is as important as picking winners.",
    ]),
    _b("Mastering the Market Cycle", "Howard Marks", 2018, HISTORY, [
        "Cycles are inevitable - extremes in sentiment create opportunity.",
        "The riskiest thing is the belief that there is no risk.",
        "Position the portfolio for the cycle stage, not the last headline.",
    ]),
    _b("Margin of Safety", "Seth Klarman", 1991, RISK, [
        "Invest with a margin of safety; the price paid protects the downside.",
        "Absolute returns and capital preservation beat relative performance.",
        "Good investing is often doing nothing and waiting for value.",
    ]),
    _b("The Intelligent Investor", "Benjamin Graham", 1949, VALUE, [
        "The market is a voting machine short-term and a weighing machine long-term.",
        "Margin of safety is the central concept of sound investing.",
        "Distinguish investment (safety + adequate return) from speculation.",
        "Defensive investors avoid leverage and overpaying for growth.",
    ]),
    _b("Security Analysis", "Benjamin Graham & David Dodd", 1934, VALUE, [
        "Analyse intrinsic value independently of market price.",
        "Insist on a margin of safety between price and value.",
        "Beware of accounting illusions and optimistic projections.",
    ]),
    _b("The Warren Buffett Way", "Robert Hagstrom", 1994, VALUE, [
        "Buy excellent businesses at fair prices and hold for the long term.",
        "Focus on durable competitive advantage (a 'moat').",
        "Mr Market's moods are opportunities, not instructions.",
    ]),
    _b("One Up On Wall Street", "Peter Lynch", 1989, VALUE, [
        "Invest in what you understand; your edge may be everyday observation.",
        "Look for companies with boring names, low institutional ownership, and growth.",
        "The big winners are held for years, not days.",
        "Know why you own a stock - the story must be told in two minutes.",
    ]),
    _b("Beating the Street", "Peter Lynch", 1993, VALUE, [
        "Do your homework; earnings and cash flow drive long-run prices.",
        "Turn over stones others ignore; the crowd usually overpays for the obvious.",
    ]),
    _b("Common Stocks and Uncommon Profits", "Philip Fisher", 1958, VALUE, [
        "Use the 'scuttlebutt' method - talk to customers and competitors.",
        "Buy great growth companies and hold them through volatility.",
        "Focus on management quality and R&D strength.",
    ]),
    _b("You Can Be a Stock Market Genius", "Joel Greenblatt", 1997, VALUE, [
        "Special situations (spinoffs, mergers, restructurings) create mispricing.",
        "Look where institutions are forced to sell for non-fundamental reasons.",
        "Concentration in your best ideas can beat broad diversification.",
    ]),
    _b("The Little Book That Beats the Market", "Joel Greenblatt", 2005, VALUE, [
        "Buy good companies (high returns on capital) at cheap prices.",
        "A simple, systematic value formula can beat emotional stock picking.",
        "Patience and consistency matter more than cleverness.",
    ]),
    _b("The Dhandho Investor", "Mohnish Pabrai", 2007, VALUE, [
        "Heads I win big, tails I don't lose much - seek asymmetric bets.",
        "Cloning the best investors' ideas is a legitimate strategy.",
        "Few bets, big bets, infrequent bets; know deeply what you own.",
    ]),
    _b("Poor Charlie's Almanack", "Charlie Munger", 2005, PSYCH, [
        "Use mental models from many disciplines to reason about markets.",
        "Invert: ask what would make this fail, then avoid it.",
        "Avoid envy, resentment and self-pity - they ruin judgement.",
    ]),
    _b("The Psychology of Money", "Morgan Housel", 2020, PSYCH, [
        "Doing well with money is about behaviour, not intelligence.",
        "Leave room for error; survival is the prerequisite for compounding.",
        "Enough is a decision; greed turns good outcomes into disasters.",
        "Tail events drive most outcomes - a few big wins dominate.",
    ]),
    _b("Same as Ever", "Morgan Housel", 2023, PSYCH, [
        "The constant is human behaviour; plan for it rather than for forecasts.",
        "Calm beats excitement; expectations should be managed, not maximised.",
    ]),
    _b("Thinking, Fast and Slow", "Daniel Kahneman", 2011, PSYCH, [
        "Loss aversion makes losses hurt ~2x more - plan exits to defuse it.",
        "Overconfidence and the planning fallacy inflate forecasts.",
        "Anchoring and recency bias distort price perception.",
        "Use checklists and base rates to override intuition.",
    ]),
    _b("Thinking in Bets", "Annie Duke", 2018, PROB, [
        "Separate decision quality from outcome quality - results lie short-term.",
        "Think in probabilities and update beliefs as evidence arrives.",
        "Pre-commit to a process to resist hindsight and tilt.",
    ]),
    _b("Fooled by Randomness", "Nassim Taleb", 2001, PROB, [
        "Much of apparent skill is luck; beware mistaking noise for signal.",
        "Survivorship bias hides the many who took the same risk and blew up.",
        "Avoid strategies with rare, catastrophic downside.",
    ]),
    _b("The Black Swan", "Nassim Taleb", 2007, RISK, [
        "Rare, extreme events dominate markets; do not rely on normal distributions.",
        "Build robustness: small positions, no fragile leverage.",
        "Exposure to positive asymmetry beats forecasting.",
    ]),
    _b("Antifragile", "Nassim Taleb", 2012, RISK, [
        "Design a system that gains from volatility rather than breaks from it.",
        "Barbell strategy: extreme safety plus small aggressive bets.",
        "Avoid the fragile middle that hides hidden leverage.",
    ]),
    _b("Skin in the Game", "Nassim Taleb", 2018, RISK, [
        "Distrust advice from those who bear no downside for being wrong.",
        "Symmetry of risk and reward keeps incentives honest.",
    ]),
    _b("Against the Gods", "Peter Bernstein", 1996, HISTORY, [
        "Risk management is the history of learning to measure and tame uncertainty.",
        "Probability, not certainty, is the foundation of sound decisions.",
        "Betting a fraction of capital (Kelly logic) maps to survival.",
    ]),
    _b("The (Mis)Behaviour of Markets", "Benoit Mandelbrot", 2004, RISK, [
        "Markets are fractal and fat-tailed; volatility clusters.",
        "Extreme moves happen far more often than Gaussian models predict.",
        "Respect wild randomness; size for the fat tail.",
    ]),
    _b("A Random Walk Down Wall Street", "Burton Malkiel", 1973, VALUE, [
        "Most active managers fail to beat low-cost index funds after costs.",
        "Markets are largely efficient; cheap diversification wins.",
        "Behavioural errors, not information gaps, cost investors dearly.",
    ]),
    _b("The Little Book of Common Sense Investing", "John Bogle", 2007, VALUE, [
        "Own the whole market cheaply; costs are the enemy of returns.",
        "Time in the market beats timing the market for most people.",
    ]),
    _b("Winning the Loser's Game", "Charles Ellis", 1985, VALUE, [
        "Active trading is a loser's game - reduce mistakes to win.",
        "Turnover, timing and costs quietly destroy returns.",
    ]),
    _b("The Elements of Investing", "Malkiel & Ellis", 2009, VALUE, [
        "Save, diversify, index and rebalance; keep it simple.",
    ]),
    _b("Extraordinary Popular Delusions and the Madness of Crowds", "Charles Mackay", 1841, HISTORY, [
        "Crowds create and destroy fortunes through shared delusion.",
        "Recognise bubbles early by the stories people tell to justify price.",
    ]),
    _b("Manias, Panics, and Crashes", "Charles Kindleberger", 1978, HISTORY, [
        "Credit expansion fuels bubbles; contraction triggers panics.",
        "Each crisis rhymes: displacement, boom, euphoria, crash, revulsion.",
    ]),
    _b("Irrational Exuberance", "Robert Shiller", 2000, HISTORY, [
        "Valuations and narratives, not fundamentals alone, drive bubbles.",
        "Beware feedback loops where rising prices create the story.",
    ]),
    _b("This Time Is Different", "Reinhart & Rogoff", 2009, HISTORY, [
        "Financial crises are frequent and share deep structural patterns.",
        "Excessive debt precedes most banking and sovereign crises.",
    ]),
    _b("Devil Take the Hindmost", "Edward Chancellor", 1999, HISTORY, [
        "Speculative manias recur across centuries in different guises.",
        "Leverage is the accelerant of every bust.",
    ]),
    _b("The Ascent of Money", "Niall Ferguson", 2008, HISTORY, [
        "Finance evolves with society; understanding history informs risk.",
        "Bubbles and innovations are inseparable over centuries.",
    ]),
    _b("A History of the United States in Five Crashes", "Scott Nations", 2017, HISTORY, [
        "Crashes are often triggered by concentrated leverage unwinding.",
        "Liquidity evaporates exactly when you need it most.",
    ]),
    _b("The Great Crash 1929", "John Kenneth Galbraith", 1955, HISTORY, [
        "Euphoria, leverage and margin debt precede the fall.",
        "After the crash, the crowd's revulsion keeps prices depressed.",
    ]),
    _b("The Big Short", "Michael Lewis", 2010, HISTORY, [
        "Few saw the subprime collapse; those who did sized up with conviction.",
        "Structural complexity hides systemic risk from most participants.",
    ]),
    _b("Liar's Poker", "Michael Lewis", 1989, HISTORY, [
        "Wall Street is a game of information and nerve as much as analysis.",
        "Incentives drive behaviour more than stated intentions.",
    ]),
    _b("Flash Boys", "Michael Lewis", 2014, MICRO, [
        "Speed and market structure create hidden costs for investors.",
        "Understanding the plumbing matters for execution quality.",
    ]),
    _b("Dark Pools", "Scott Patterson", 2012, MICRO, [
        "Much of modern liquidity is invisible and algorithmic.",
        "HFT provides liquidity but changes the microstructure regime.",
    ]),
    _b("The Quants", "Scott Patterson", 2010, QUANT, [
        "Quant models work until crowded trades unwind them violently.",
        "Diversification fails when correlations go to one in a crisis.",
    ]),
    _b("More Money Than God", "Sebastian Mallaby", 2010, HISTORY, [
        "Hedge funds succeed via edge, leverage and risk control - not luck alone.",
        "Macro flexibility and concentration define the best managers.",
    ]),
    _b("Inside the House of Money", "Steven Drobny", 2006, HISTORY, [
        "Global macro trades themes: rates, currencies, and policy.",
        "Position for asymmetry; let the market prove you right.",
    ]),
    _b("The Invisible Hands", "Steven Drobny", 2010, HISTORY, [
        "Top macro managers blend fundamentals with price and risk.",
        "Adapt conviction to the prevailing regime.",
    ]),
    _b("When Genius Failed", "Roger Lowenstein", 2000, RISK, [
        "Excessive leverage makes small errors fatal (LTCM).",
        "Models that ignore liquidity and correlation invite ruin.",
        "Concentration plus leverage is a time bomb.",
    ]),
    _b("The Greatest Trade Ever", "Gregory Zuckerman", 2009, HISTORY, [
        "The best trades are contrarian, well-researched and sized to matter.",
        "Asymmetric payoffs reward the patient bear.",
    ]),
    _b("The Man Who Solved the Market", "Gregory Zuckerman", 2019, QUANT, [
        "Systematic, data-driven edges compound over thousands of trades.",
        "Risk control and enormous sample sizes beat prediction.",
        "Signals are small and statistical - discipline extracts them.",
    ]),
    _b("Advances in Financial Machine Learning", "Marcos Lopez de Prado", 2018, QUANT, [
        "Financial data is noisy and non-IID; beware backtest overfitting.",
        "Use purged cross-validation and deflated Sharpe ratios.",
        "Ml must respect the serial dependence of markets.",
    ]),
    _b("Machine Learning for Asset Managers", "Marcos Lopez de Prado", 2020, QUANT, [
        "Most 'discovered' factors are false positives - correct for multiplicity.",
        "Clustering reveals structure that correlations miss.",
    ]),
    _b("Evidence-Based Technical Analysis", "David Aronson", 2006, QUANT, [
        "Data mining produces spurious rules; test against a null.",
        "Only repeatable, statistically significant edges are real.",
    ]),
    _b("Quantitative Trading", "Ernest Chan", 2008, QUANT, [
        "Start with a simple, robust mean-reversion or momentum strategy.",
        "Beware survivorship bias and look-ahead in backtests.",
        "Execution costs and slippage decide marginal strategies.",
    ]),
    _b("Algorithmic Trading", "Ernest Chan", 2013, QUANT, [
        "Mean reversion works best in ranges; momentum in trends.",
        "Regime awareness and risk management drive algorithmic P&L.",
    ]),
    _b("Machine Trading", "Ernest Chan", 2017, QUANT, [
        "Diversify across many small uncorrelated models.",
        "Automate risk limits; humans cannot react fast enough.",
    ]),
    _b("Building Winning Algorithmic Trading Systems", "Kevin Davey", 2014, SYSTEM, [
        "Develop, backtest, then walk-forward test before risking capital.",
        "Avoid curve-fitting; simpler systems generalise better.",
        "Keep a portfolio of strategies to smooth equity.",
    ]),
    _b("Trading Systems and Methods", "Perry Kaufman", 2013, SYSTEM, [
        "Trend, mean-reversion and volatility systems have distinct regimes.",
        "Robustness across parameters and markets is the true test.",
        "Diversification across systems reduces drawdown.",
    ]),
    _b("The Encyclopedia of Trading Strategies", "Katz & McCormick", 2000, SYSTEM, [
        "Systematically compare entry/exit logic with out-of-sample tests.",
        "Most indicators add little edge once tested rigorously.",
    ]),
    _b("The Mathematics of Money Management", "Ralph Vince", 1992, RISK, [
        "Optimal f is a risk ceiling, not a target - trade below it.",
        "Drawdown grows faster than returns as leverage rises.",
    ]),
    _b("Fortune's Formula", "William Poundstone", 2005, RISK, [
        "The Kelly criterion sizes bets to maximise long-run growth.",
        "Over-betting the Kelly fraction invites ruin.",
        "Edges compound only if you survive the variance.",
    ]),
    _b("Trading and Exchanges", "Larry Harris", 2002, MICRO, [
        "Markets exist to provide liquidity and price discovery.",
        "Understand order types, spreads and who takes the other side.",
        "Informed vs uninformed traders determine your edge.",
    ]),
    _b("Empirical Market Microstructure", "Joel Hasbrouck", 2007, MICRO, [
        "Price moves are driven by order flow information.",
        "Estimate adverse selection to avoid toxic fills.",
    ]),
    _b("Trades, Quotes and Prices", "Bouchaud et al.", 2018, MICRO, [
        "Order flow is long-memory and clustered; impact is concave.",
        "Liquidity is fragile and disappears under stress.",
    ]),
    _b("Options, Futures and Other Derivatives", "John Hull", 1988, OPTIONS, [
        "Derivatives price risk; understand payoff and greeks before trading.",
        "No-arbitrage relationships discipline derivative pricing.",
    ]),
    _b("Option Volatility & Pricing", "Sheldon Natenberg", 1988, OPTIONS, [
        "Trade volatility as an asset, not just direction.",
        "The greeks quantify how a position responds as markets move.",
        "Sell premium only with defined, survivable risk.",
    ]),
    _b("Volatility Trading", "Euan Sinclair", 2008, OPTIONS, [
        "Edge comes from mispriced implied vs realised volatility.",
        "Size option positions for the fat tails of volatility.",
    ]),
    _b("The Options Playbook", "Brian Overby", 2007, OPTIONS, [
        "Match strategy to market view: direction, magnitude and time.",
        "Covered calls and spreads reduce cost but cap upside - know the tradeoff.",
    ]),
    _b("Trading Volatility", "Colin Bennett", 2014, OPTIONS, [
        "Volatility mean-reverts; buy low, sell high implied vol carefully.",
        "Hedge tail risk; vol spikes faster than it decays.",
    ]),
    _b("Option Market Making", "Allen Baird", 1992, OPTIONS, [
        "Market making profits from spread and hedge, not direction.",
        "Inventory risk is the central enemy of the maker.",
    ]),
    _b("The Signal and the Noise", "Nate Silver", 2012, PROB, [
        "Distinguish signal from noise; most forecasts are overconfident.",
        "Probabilistic thinking and Bayesian updating improve decisions.",
        "Beware pundits who are rewarded for certainty.",
    ]),
    _b("Superforecasting", "Philip Tetlock", 2015, PROB, [
        "Break problems into small, updatable probabilistic pieces.",
        "Frequent, small belief updates beat bold predictions.",
        "Keep score and learn from calibration.",
    ]),
    _b("The Art of Strategy", "Avinash Dixit & Barry Nalebuff", 2008, PROB, [
        "Think about others' likely reactions before you act.",
        "Backward induction and credible commitments shape outcomes.",
    ]),
    _b("Thinking Strategically", "Dixit & Nalebuff", 1991, PROB, [
        "Anticipate the counter-move; markets are games of reaction.",
    ]),
    _b("The Zurich Axioms", "Max Gunther", 1985, SPEC, [
        "Risk is unavoidable and necessary; take it deliberately.",
        "Always bet on the outcome, not on being right; cut and run on trouble.",
        "Diversify only when you do not understand the bet.",
    ]),
    _b("The Battle for Investment Survival", "Gerald Loeb", 1935, SPEC, [
        "The first rule is to protect capital; profits come second.",
        "Cut losses and let winners run; do not average down.",
    ]),
    _b("The Master Swing Trader", "Alan Farley", 2000, TECH, [
        "Trade the pattern within its context of trend and range.",
        "Multiple timeframes align swing entries.",
    ]),
    _b("How to Make Money in Stocks", "William O'Neil", 1988, TREND, [
        "Buy high-growth leaders breaking out of sound bases on volume (CANSLIM).",
        "Cut every loss at 7-8% below your purchase price.",
        "Buy when the general market is in a confirmed uptrend.",
        "Concentrate on the very best names, not fallen angels.",
    ]),
    _b("How to Trade in Stocks", "Jesse Livermore", 1940, SPEC, [
        "Trade with the line of least resistance and confirm with volume.",
        "Add to winners at pivotal points; never add to losers.",
        "Use the market's own behaviour as your guide, not tips or opinions.",
    ]),
    _b("Trading Basics", "Thomas Bulkowski", 2017, TECH, [
        "Encyclopedia of chart patterns with measured probabilities, not certainties.",
        "Evaluate pattern performance statistically across many samples.",
    ]),
    _b("Technical Analysis: The Complete Resource", "Kirk Northington", 2009, TECH, [
        "Set-ups are high-probability pullbacks within a larger trend.",
        "Use support/resistance and volume to time entries.",
    ]),
    _b("Sentiment in the Forex Market", "Jamie Saettele", 2012, MICRO, [
        "Crowd sentiment extremes mark turning points.",
        "Trade against the consensus when positioning is stretched.",
    ]),
    _b("Day Trading and Swing Trading the Currency Market", "Kathy Lien", 2005, MICRO, [
        "Currency trends reflect rate differentials and capital flows.",
        "Respect session ranges; volatility clusters around data releases.",
    ]),
    _b("Intermarket Analysis", "John Murphy", 2004, MICRO, [
        "Markets are linked: bonds, currencies, commodities and equities interact.",
        "Relate your symbol to the macro backdrop before trading.",
    ]),
    _b("The Handbook of Technical Analysis", "Various", 2015, TECH, [
        "Combine trend, momentum and volume for robust signals.",
        "Confirm every setup with the higher timeframe.",
    ]),
    _b("Pit Bull: Lessons from Wall Street's Champion Day Trader", "Martin Schwartz", 1998, SPEC, [
        "Trade big only with an edge and a plan; focus intensely.",
        "Cut losses instantly; the first loss is the best loss.",
        "A short-term trader's enemy is a wandering mind.",
    ]),
    _b("The Compleat Day Trader", "Jake Bernstein", 1995, SYSTEM, [
        "Day trading requires a precise plan, discipline and risk control.",
        "Trade the same setups repetitively and measure results.",
    ]),
    _b("Swing Trading for Dummies", "Omar Bassal", 2008, SYSTEM, [
        "Swing trading balances time commitment with trend capture.",
        "Use stops and position sizing appropriate to overnight risk.",
    ]),
    _b("The New Science of Technical Analysis", "Thomas DeMark", 1994, TECH, [
        "Objective price-sequence rules reduce subjectivity.",
        "Sequential and TD-line rules time exhaustion points.",
    ]),
    _b("Schwager on Futures: Technical Analysis", "Jack Schwager", 1996, TECH, [
        "Test every indicator; most add little to a sound framework.",
        "Charts are a framework for risk, not a crystal ball.",
    ]),
    _b("The Complete Guide to the Futures Market", "Schwager & Etzkorn", 2017, SYSTEM, [
        "Futures trading demands strict risk and margin management.",
        "Trend following and spreads offer distinct edges.",
    ]),
    _b("Investing: The Last Liberal Art", "Robert Hagstrom", 2000, VALUE, [
        "Latticework thinking: combine disciplines to value businesses.",
        "Great investing is probabilistic and multi-model.",
    ]),
    _b("The Little Book of Behavioral Investing", "James Montier", 2010, PSYCH, [
        "Our brains are poorly wired for markets; systems beat willpower.",
        "Avoid action bias and overtrading; do less, think more.",
    ]),
    _b("The Little Book of Valuation", "Aswath Damodaran", 2011, VALUE, [
        "Every valuation is a story tied to numbers; be explicit about both.",
        "Relative valuation is a shortcut but ignores the story.",
    ]),
    _b("Narrative Economics", "Robert Shiller", 2019, HISTORY, [
        "Stories spread like epidemics and move markets.",
        "Detecting the dominant narrative helps anticipate flows.",
    ]),
]

_BY_TITLE = {b["title"]: b for b in BOOKS}


def all_books() -> list[dict]:
    return BOOKS


def categories() -> list[str]:
    return CATEGORIES


def stats() -> dict:
    return {"books": len(BOOKS), "lessons": sum(len(b["lessons"]) for b in BOOKS),
            "categories": len(CATEGORIES)}


def search(q: str | None = None, category: str | None = None, limit: int = 500) -> dict:
    ql = (q or "").strip().lower()
    out = []
    for b in BOOKS:
        if category and b["category"] != category:
            continue
        if ql:
            blob = (b["title"] + " " + b["author"] + " " + b["category"] + " " +
                    " ".join(b["lessons"])).lower()
            if ql not in blob:
                continue
        out.append(b)
    return {"total": len(out), "rows": out[:limit], "stats": stats()}


def for_category(category: str, limit: int = 8) -> list[str]:
    lessons: list[str] = []
    for b in BOOKS:
        if b["category"] == category:
            lessons.extend((b["title"], l) for l in b["lessons"])
    return lessons[:limit]


# ------------------------------------------------------------------ coach
def _situations(ctx: dict) -> list[dict]:
    """Map the current state to relevant knowledge categories + rationale."""
    out: list[dict] = []
    dd = abs(float(ctx.get("drawdown_pct") or 0))
    wr = ctx.get("win_rate")
    streak = int(ctx.get("loss_streak") or 0)
    vol = float(ctx.get("volatility_pct") or 0)
    regime = str(ctx.get("regime") or "").upper()
    mood = str(ctx.get("mood") or "").upper()
    positions = int(ctx.get("open_positions") or 0)
    exposure = float(ctx.get("gross_pct") or 0)

    if dd >= 3 or streak >= 3:
        out.append({"tag": "Drawdown / losing streak", "categories": [RISK, PSYCH],
                    "note": "Protect capital first: size down, cut the bleed, review the plan."})
    if wr is not None and wr < 0.4 and (ctx.get("trades") or 0) >= 10:
        out.append({"tag": "Low win rate", "categories": [SYSTEM, PSYCH],
                    "note": "Check expectancy, not win rate; ensure setups are A-grade."})
    if vol >= 4:
        out.append({"tag": "High volatility", "categories": [RISK, PROB],
                    "note": "Volatility expands risk - reduce size, widen stops, expect fat tails."})
    if regime in ("TREND_UP", "TREND_DOWN", "TRENDING"):
        out.append({"tag": "Trending market", "categories": [TREND, TECH],
                    "note": "Trade with the trend; buy pullbacks or breakouts with volume."})
    if regime in ("RANGE", "RANGING", "CHOP"):
        out.append({"tag": "Range / chop", "categories": [TECH, MICRO],
                    "note": "Mean-revert at extremes; avoid chasing breakouts that fail."})
    if mood in ("STRESSED", "FRUSTRATED", "TILTED", "HALTED"):
        out.append({"tag": "Emotional state", "categories": [PSYCH],
                    "note": "Step back; the next trade should be tiny or not taken."})
    if exposure > 150:
        out.append({"tag": "High gross exposure", "categories": [RISK, MICRO],
                    "note": "Leverage amplifies both tails - consider trimming into strength."})
    if positions == 0:
        out.append({"tag": "Flat / no positions", "categories": [SPEC, PROB],
                    "note": "Waiting is a position; only enter elite setups."})
    if not out:
        out.append({"tag": "Steady state", "categories": [RISK, SYSTEM],
                    "note": "Stay consistent, follow the plan, keep risk fixed and small."})
    return out


def coach(ctx: dict, per_category: int = 3, seed: int | None = None) -> dict:
    """Return grounded, situation-relevant principles + a risk checklist."""
    rng = random.Random(seed if seed is not None else int(time.time() // 900))
    situations = _situations(ctx)
    picks: list[dict] = []
    seen: set[str] = set()
    for s in situations:
        for cat in s["categories"]:
            pool = [b for b in BOOKS if b["category"] == cat]
            rng.shuffle(pool)
            for b in pool[:per_category]:
                for lesson in b["lessons"][:2]:
                    if lesson in seen:
                        continue
                    seen.add(lesson)
                    picks.append({"book": b["title"], "author": b["author"],
                                  "category": b["category"], "lesson": lesson, "for": s["tag"]})
    # a rotating "quote of the day"
    qbook = rng.choice(BOOKS)
    quote = {"book": qbook["title"], "author": qbook["author"], "lesson": rng.choice(qbook["lessons"])}

    checklist = [
        "Risk per trade <= 1% of equity; total open risk <= 3-6%.",
        "Every position has a predefined stop and target (R multiple).",
        "Trade with the higher-timeframe trend; require confirmation.",
        "Size down in high volatility; never average down.",
        "Cap daily loss; stop trading after it is hit.",
        "No revenge trades, no FOMO chases, no unplanned adds.",
        "Journal every trade with the reason and the outcome.",
    ]
    return {
        "situations": [{"tag": s["tag"], "note": s["note"]} for s in situations],
        "principles": picks[:24],
        "checklist": checklist,
        "quote": quote,
        "context": ctx,
        "updated": time.time(),
    }


def context_block(ctx: dict, limit: int = 6) -> str:
    """Short grounding text for the LLM analyst prompt."""
    c = coach(ctx)
    lines = [f"- {p['lesson']} ({p['book']})" for p in c["principles"][:limit]]
    return "Grounded trading principles relevant now:\n" + "\n".join(lines) if lines else ""
