# prometheus stack module

- Module id: `prometheus`
- Module repo: `prometheus-stack-module`
- Source repo: none declared
- Lifecycle: `active`

## Owned overlays
- `stack.compose/prometheus.yml`
- `stack.config/prometheus`

## Dependencies
- `stack-foundation`

## Validation

```sh
./tests/validate.sh
```

## Lifecycle

`active` modules are expected to keep `stack.module.json`, owned overlays, and `tests/validate.sh` in sync.
