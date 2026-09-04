# Citations

Every constant, formula family, and honesty rule in QuantDesk traces to one of
the works below. Entries are BibTeX-style for convenience; where a DOI or
arXiv id is known it is given, otherwise the venue and year. No text from
these works is reproduced in the code; formulas are restated in the
library's own notation (see `NOTICE.md`, including its caveat on the
Alpha101 entries that have no cross-sectional operator).

## Formulaic alphas

```bibtex
@article{kakushadze2016alphas,
  title   = {101 Formulaic Alphas},
  author  = {Kakushadze, Zura},
  journal = {Wilmott Magazine},
  volume  = {2016},
  number  = {84},
  pages   = {72--81},
  year    = {2016},
  note    = {arXiv:1601.00991. The paper states the alphas are proprietary to
             WorldQuant LLC and were published with its permission; this
             library re-implements adapted time-series forms restated in its
             own operator notation and does not reproduce the paper's text,
             notation or cross-sectional forms (see NOTICE.md).}
}
```

## Time-series momentum and volatility

```bibtex
@article{moskowitz2012tsmom,
  title   = {Time Series Momentum},
  author  = {Moskowitz, Tobias J. and Ooi, Yao Hua and Pedersen, Lasse Heje},
  journal = {Journal of Financial Economics},
  volume  = {104},
  number  = {2},
  pages   = {228--250},
  year    = {2012},
  doi     = {10.1016/j.jfineco.2011.11.003}
}

@article{harvey2022crypto,
  title   = {An Investor's Guide to Crypto},
  author  = {Harvey, Campbell R. and Abou Zeid, Tarek and Draaisma, Teun and
             Luk, Martin and Neville, Henry and Rzym, Andre and
             van Hemert, Otto},
  journal = {The Journal of Portfolio Management},
  volume  = {49},
  number  = {1},
  year    = {2022},
  note    = {Source of the EWMA center-of-mass (5d/180d), two-bar lag,
             22/65/261-day lookbacks, 22d+261d blend and 10 percent
             volatility target used in quantdesk.factors.tsmom.}
}

@article{yang2000drift,
  title   = {Drift-Independent Volatility Estimation Based on High, Low, Open,
             and Close Prices},
  author  = {Yang, Dennis and Zhang, Qiang},
  journal = {The Journal of Business},
  volume  = {73},
  number  = {3},
  pages   = {477--491},
  year    = {2000},
  doi     = {10.1086/209650}
}

@article{rogers1991variance,
  title   = {Estimating Variance From High, Low and Closing Prices},
  author  = {Rogers, L. C. G. and Satchell, S. E.},
  journal = {The Annals of Applied Probability},
  volume  = {1},
  number  = {4},
  pages   = {504--512},
  year    = {1991},
  doi     = {10.1214/aoap/1177005835}
}

@article{molnar2012range,
  title   = {Properties of range-based volatility estimators},
  author  = {Molnar, Peter},
  journal = {International Review of Financial Analysis},
  volume  = {23},
  pages   = {20--29},
  year    = {2012},
  doi     = {10.1016/j.irfa.2011.06.012}
}

@book{grinold2000active,
  title     = {Active Portfolio Management: A Quantitative Approach for
               Producing Superior Returns and Controlling Risk},
  author    = {Grinold, Richard C. and Kahn, Ronald N.},
  edition   = {2},
  publisher = {McGraw-Hill},
  year      = {2000},
  note      = {Alpha = IC x volatility x score; winsorized z-scores.}
}

@techreport{twosigma2018factorlens,
  title       = {Introducing the Two Sigma Factor Lens},
  author      = {{Two Sigma Investments}},
  institution = {Two Sigma},
  year        = {2018},
  url         = {https://www.twosigma.com/wp-content/uploads/Introducing-the-Two-Sigma-Factor-Lens.10.18.pdf},
  note        = {Rolling EWMA regression beta with shrinkage; a risk lens,
                 not an alpha library.}
}
```

## Market microstructure

```bibtex
@article{stoikov2018microprice,
  title   = {The micro-price: a high-frequency estimator of future prices},
  author  = {Stoikov, Sasha},
  journal = {Quantitative Finance},
  volume  = {18},
  number  = {12},
  pages   = {1959--1966},
  year    = {2018},
  note    = {arXiv:1708.03135 (2017)}
}

@article{cont2014ofi,
  title   = {The Price Impact of Order Book Events},
  author  = {Cont, Rama and Kukanov, Arseniy and Stoikov, Sasha},
  journal = {Journal of Financial Econometrics},
  volume  = {12},
  number  = {1},
  pages   = {47--88},
  year    = {2014},
  note    = {arXiv:1011.6402. Contemporaneous R^2 on the order of tens of
             percent; predictive R^2 is a different, much smaller quantity.}
}

@article{gould2016queue,
  title   = {Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit
             Order Book},
  author  = {Gould, Martin D. and Bonart, Julius},
  journal = {Market Microstructure and Liquidity},
  volume  = {2},
  number  = {2},
  year    = {2016},
  note    = {arXiv:1512.03492}
}

@article{silantyev2019orderflow,
  title   = {Order flow analysis of cryptocurrency markets},
  author  = {Silantyev, Eduard},
  journal = {Digital Finance},
  volume  = {1},
  pages   = {191--218},
  year    = {2019},
  doi     = {10.1007/s42521-019-00007-w}
}

@article{xu2019mlofi,
  title   = {Multi-Level Order-Flow Imbalance in a Limit Order Book},
  author  = {Xu, Ke and Gould, Martin D. and Howison, Sam D.},
  journal = {Market Microstructure and Liquidity},
  year    = {2019},
  note    = {arXiv:1907.06230}
}

@article{cont2023crossimpact,
  title   = {Cross-impact of order flow imbalance in equity markets},
  author  = {Cont, Rama and Cucuringu, Mihai and Zhang, Chao},
  journal = {Quantitative Finance},
  volume  = {23},
  number  = {10},
  year    = {2023},
  note    = {arXiv:2112.13213}
}

@article{kyle1985auctions,
  title   = {Continuous Auctions and Insider Trading},
  author  = {Kyle, Albert S.},
  journal = {Econometrica},
  volume  = {53},
  number  = {6},
  pages   = {1315--1335},
  year    = {1985},
  doi     = {10.2307/1913210}
}

@article{amihud2002illiquidity,
  title   = {Illiquidity and stock returns: cross-section and time-series
             effects},
  author  = {Amihud, Yakov},
  journal = {Journal of Financial Markets},
  volume  = {5},
  number  = {1},
  pages   = {31--56},
  year    = {2002},
  doi     = {10.1016/S1386-4181(01)00024-6}
}
```

## Market making and execution

```bibtex
@article{avellaneda2008hft,
  title   = {High-frequency trading in a limit order book},
  author  = {Avellaneda, Marco and Stoikov, Sasha},
  journal = {Quantitative Finance},
  volume  = {8},
  number  = {3},
  pages   = {217--224},
  year    = {2008},
  doi     = {10.1080/14697680701381228}
}

@misc{hummingbot,
  title  = {Hummingbot: open-source market making framework},
  author = {{Hummingbot Foundation}},
  year   = {2019--2026},
  url    = {https://github.com/hummingbot/hummingbot},
  note   = {Apache License 2.0. Parameter vocabulary and the linear
            inventory-skew rule are referenced by name; no code is included.}
}

@techreport{frazzini2018tradingcosts,
  title       = {Trading Costs},
  author      = {Frazzini, Andrea and Israel, Ronen and Moskowitz, Tobias J.},
  institution = {AQR Capital Management},
  year        = {2018},
  note        = {Participation-rate impact curve; short-term reversal is the
                 one classic factor that does not survive institutional
                 costs. Referenced in docs/FACTOR_VERDICTS.md.}
}
```

## Research discipline

```bibtex
@misc{robotwealth2019turnover,
  title  = {A Simple, Effective Way to Manage Turnover and Not Get Killed by
            Costs},
  author = {{Robot Wealth}},
  year   = {2019},
  url    = {https://robotwealth.com/a-simple-effective-way-to-manage-turnover-and-not-get-killed-by-costs/},
  note   = {No-trade band as a first-class turnover control.}
}

@misc{robotwealth2020cryptoalphas,
  title  = {Quantifying and Combining Crypto Alphas},
  author = {{Robot Wealth}},
  year   = {2020},
  url    = {https://robotwealth.com/quantifying-and-combining-crypto-alphas/},
  note   = {Two-stage evaluation funnel.}
}

@misc{databento2023hft,
  title  = {HFT-style feature engineering with scikit-learn},
  author = {{Databento}},
  year   = {2023},
  url    = {https://databento.com/blog/hft-sklearn-python},
  note   = {Contemporaneous versus predictive R^2.}
}

@article{bailey2014deflated,
  title   = {The Deflated Sharpe Ratio: Correcting for Selection Bias,
             Backtest Overfitting, and Non-Normality},
  author  = {Bailey, David H. and Lopez de Prado, Marcos},
  journal = {The Journal of Portfolio Management},
  volume  = {40},
  number  = {5},
  pages   = {94--107},
  year    = {2014},
  note    = {Why trial counts belong beside every reported Sharpe.}
}

@book{lopezdeprado2018advances,
  title     = {Advances in Financial Machine Learning},
  author    = {Lopez de Prado, Marcos},
  publisher = {Wiley},
  year      = {2018},
  note      = {Purged and embargoed cross-validation (roadmap item).}
}
```

## Crypto factor literature referenced in the verdicts

```bibtex
@article{liu2022cryptofactors,
  title   = {Common Risk Factors in Cryptocurrency},
  author  = {Liu, Yukun and Tsyvinski, Aleh and Wu, Xi},
  journal = {The Journal of Finance},
  volume  = {77},
  number  = {2},
  pages   = {1133--1177},
  year    = {2022},
  doi     = {10.1111/jofi.13119}
}

@article{alexander2020leadlag,
  title   = {Price discovery in Bitcoin: The impact of unregulated markets},
  author  = {Alexander, Carol and Heck, Daniel F.},
  journal = {Journal of Financial Stability},
  volume  = {50},
  pages   = {100776},
  year    = {2020},
  doi     = {10.1016/j.jfs.2020.100776}
}

@techreport{bis2023carry,
  title       = {Crypto carry},
  author      = {{Bank for International Settlements}},
  number      = {BIS Working Paper 1087},
  year        = {2023},
  url         = {https://www.bis.org/publ/work1087.pdf}
}

@techreport{twosigma2021regime,
  title       = {A Machine Learning Approach to Regime Modeling},
  author      = {{Two Sigma Investments}},
  institution = {Two Sigma},
  year        = {2021},
  url         = {https://www.twosigma.com/wp-content/uploads/2021/10/Machine-Learning-Approach-to-Regime-Modeling_.pdf},
  note        = {The paper itself states the model is not predictive.}
}
```
