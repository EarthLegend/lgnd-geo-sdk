# Energy analyst

A Pydantic AI agent for an analyst at an energy research firm, who tracks new solar farms,
battery storage, substations and wind farms in the US. It prints its thinking and each tool call as
they happen, then the answer as it is written, with
[`_printing.py`](https://github.com/EarthLegend/lgnd-geo-sdk/blob/main/examples/pydantic_ai/_printing.py),
a helper the examples share.

```
python examples/pydantic_ai/energy_analyst.py "Find solar farms built in central Illinois since 2021."
```

```python
--8<-- "examples/pydantic_ai/energy_analyst.py"
```
