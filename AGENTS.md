# BaseMem Global Executive Protocol

## Start Of Session
Run these commands before doing project work:

1. `kb session context`
2. `kb planet read "<topic>"` when the active topic is known

## During Session
Use planets as canonical task state and moons as transcript archives.

- `kb session turn --topic "<topic>" --message "<short activity>" --agent-id "<id>"`
- `kb planet set "<topic>" --state "<current state>" --next "<next step>"`
- `kb note "<topic>" --type decision|fact|task|issue --message "<durable note>" --agent-id "<id>"`

## End Of Session
Run these before exiting:

1. `kb planet compact "<topic>" --agent-id "<id>"`
2. `kb session sync --topic "<topic>" --agent-id "<id>"`

