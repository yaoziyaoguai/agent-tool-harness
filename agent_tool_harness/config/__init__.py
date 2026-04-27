"""配置加载与 spec 数据结构。

config 层只负责把 YAML 转成结构化对象并做基础字段校验，不负责审计、执行或评判。
这样可以保证同一份用户项目配置被 audit、generator、runner 复用。
"""
