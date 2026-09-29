import { createCampusRuntime } from "../adapters/campus/runtime";

/** 进程级校园适配器单例：App 外壳与登录组件共享同一 runtime（会话状态机、
 *  采集与 Cookie 镜像同源）。测试经 vi.mock 替换本模块。 */
export const campus = createCampusRuntime().adapter;
