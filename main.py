import json
import os
import time
import asyncio
import aiohttp
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Set

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.api.message_components import Plain


@register(
    "astrbot_plugin_csbaoyan",
    "Soulter",
    "查询最近计算机保研信息的插件",
    "1.0.0",
    "https://github.com/Soulter/astrbot_plugin_csbaoyan",
)
class BaoyanPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}

        # 数据目录
        self.data_dir = os.path.join("data", "csbaoyan")
        os.makedirs(self.data_dir, exist_ok=True)

        # 数据源和配置
        self.data_sources = {}
        self.default_source = None
        self.remote_url = "https://ddl.csbaoyan.top/config/schools.json"
        self.last_update_time = 0  # 最后更新时间戳
        self.update_interval = (
            self.config.get("update_interval", 10) * 60
        )  # 默认10分钟，转换为秒
        self.max_display_items = self.config.get("max_display_items", 10)

        # 订阅功能相关
        self.subscriptions = {}  # 用户订阅 {unified_msg_origin: set(tag1, tag2...)}
        self.subscription_file = os.path.join(self.data_dir, "subscriptions.json")
        self.known_programs = set()  # 已知项目的ID集合，用于检测新增项目
        self.known_programs_file = os.path.join(self.data_dir, "known_programs.json")
        self.notification_interval = 10  # 通知间隔时间，单位秒
        self.last_notification_time = 0

        # 加载订阅数据
        self.load_subscriptions()
        self.load_known_programs()

        # 初始加载数据
        self.load_data_sources()

        # 启动自动更新和通知任务
        self.update_task = asyncio.create_task(self.auto_update_task())
        self.notification_task = asyncio.create_task(self.notification_check_task())

    def load_subscriptions(self):
        """从文件加载订阅信息"""
        if os.path.exists(self.subscription_file):
            try:
                with open(self.subscription_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 将列表转换为集合
                    self.subscriptions = {k: set(v) for k, v in data.items()}
                logger.info(f"已加载 {len(self.subscriptions)} 个用户的订阅信息")
            except Exception as e:
                logger.error(f"加载订阅数据出错: {e}")
                self.subscriptions = {}
        else:
            logger.info("订阅数据文件不存在，将创建新的订阅数据")
            self.subscriptions = {}
            self.save_subscriptions()

    def save_subscriptions(self):
        """保存订阅信息到文件"""
        try:
            # 将集合转换为列表以便JSON序列化
            serializable_data = {k: list(v) for k, v in self.subscriptions.items()}
            with open(self.subscription_file, "w", encoding="utf-8") as f:
                json.dump(serializable_data, f, ensure_ascii=False, indent=4)
            logger.info("订阅信息已保存")
        except Exception as e:
            logger.error(f"保存订阅信息出错: {e}")

    def load_known_programs(self):
        """从文件加载已知项目ID"""
        if os.path.exists(self.known_programs_file):
            try:
                with open(self.known_programs_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.known_programs = set(data)
                logger.info(f"已加载 {len(self.known_programs)} 个已知项目ID")
            except Exception as e:
                logger.error(f"加载已知项目数据出错: {e}")
                self.known_programs = set()
        else:
            logger.info("已知项目数据文件不存在，将创建新的数据")
            self.known_programs = set()
            self.save_known_programs()

    def save_known_programs(self):
        """保存已知项目ID到文件"""
        try:
            with open(self.known_programs_file, "w", encoding="utf-8") as f:
                json.dump(list(self.known_programs), f, ensure_ascii=False, indent=4)
            logger.info("已知项目ID已保存")
        except Exception as e:
            logger.error(f"保存已知项目ID出错: {e}")

    async def auto_update_task(self):
        """自动更新数据源的任务"""
        while True:
            try:
                # 检查是否需要更新
                current_time = time.time()
                if current_time - self.last_update_time >= self.update_interval:
                    logger.info("正在自动更新保研信息数据...")
                    await self.update_data_from_remote()

                # 等待下一次检查
                await asyncio.sleep(60)  # 每分钟检查一次是否需要更新
            except Exception as e:
                logger.error(f"自动更新保研信息数据出错: {e}")
                await asyncio.sleep(60)  # 出错后等待5分钟再试

    async def notification_check_task(self):
        """定期检查并发送通知的任务"""
        while True:
            try:
                current_time = time.time()
                # 检查是否需要发送通知
                if (
                    current_time - self.last_notification_time
                    >= self.notification_interval
                ):
                    logger.info("开始检查并发送保研信息通知...")

                    # 获取所有数据源的项目
                    all_programs = []
                    for source, programs in self.data_sources.items():
                        all_programs.extend(programs)

                    # 检查新增的项目和即将到期的项目
                    await self.check_and_send_notifications(all_programs)

                    self.last_notification_time = current_time
                    logger.info("保研信息通知检查完成")

                # 等待下一次检查
                await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"通知检查任务出错: {e}")
                await asyncio.sleep(180)

    async def check_and_send_notifications(self, programs):
        """检查并发送通知"""
        if not self.subscriptions:
            logger.info("没有用户订阅，跳过通知发送")
            return

        # 收集所有新增项目和即将到期项目
        new_programs = []
        upcoming_programs = []
        now = datetime.now(timezone(timedelta(hours=8)))

        # 生成当前所有项目的ID集合
        current_program_ids = set()

        for program in programs:
            # 生成唯一项目ID
            program_id = self.generate_program_id(program)
            current_program_ids.add(program_id)

            # 检查是否是新项目
            if program_id not in self.known_programs:
                new_programs.append(program)

            # 检查是否是即将到期的项目（3天内）
            try:
                deadline_str = program.get("deadline", "")
                if deadline_str:
                    deadline = self.parse_deadline(deadline_str)
                    if deadline:
                        diff = deadline - now
                        # 如果在3天内即将到期
                        if 0 < diff.total_seconds() <= 3 * 24 * 3600:
                            upcoming_programs.append(program)
            except Exception as e:
                logger.error(f"检查项目截止日期出错: {e}")

        # 更新已知项目列表并保存
        self.known_programs = current_program_ids
        self.save_known_programs()

        # 按用户发送通知
        for unified_msg_origin, tags in self.subscriptions.items():
            await self.send_notifications_to_user(
                unified_msg_origin, new_programs, upcoming_programs, tags
            )

    async def send_notifications_to_user(
        self, unified_msg_origin, new_programs, upcoming_programs, user_tags
    ):
        """向特定用户发送通知"""
        # 如果用户没有指定标签，则接收所有通知
        receive_all = len(user_tags) == 0

        # 筛选符合用户标签的新项目
        filtered_new_programs = []
        if new_programs:
            for program in new_programs:
                program_tags = set(program.get("tags", []))
                if receive_all or any(tag in program_tags for tag in user_tags):
                    filtered_new_programs.append(program)

        # 筛选符合用户标签的即将到期项目
        filtered_upcoming_programs = []
        if upcoming_programs:
            for program in upcoming_programs:
                program_tags = set(program.get("tags", []))
                if receive_all or any(tag in program_tags for tag in user_tags):
                    filtered_upcoming_programs.append(program)

        # 发送新项目通知
        if filtered_new_programs:
            message = "📢 【保研信息】有新增的保研项目！\n\n"
            for i, program in enumerate(filtered_new_programs[:5], 1):
                message += f"{i}. {self.format_program_text(program)}\n"

            if len(filtered_new_programs) > 5:
                message += f"\n...等共 {len(filtered_new_programs)} 个新项目。请使用 /baoyan list 查看更多。"

            try:
                await self.context.send_message(
                    unified_msg_origin, MessageChain(chain=[Plain(message)])
                )
                logger.info(f"已发送新项目通知给用户 {unified_msg_origin}")
            except Exception as e:
                logger.error(f"发送新项目通知失败: {e}")

        # 发送即将到期项目通知
        if filtered_upcoming_programs:
            message = "⏰ 【保研信息】以下项目将在3天内截止！\n\n"
            for i, program in enumerate(filtered_upcoming_programs[:5], 1):
                message += f"{i}. {self.format_program_text(program)}\n"

            if len(filtered_upcoming_programs) > 5:
                message += f"\n...等共 {len(filtered_upcoming_programs)} 个项目即将截止。请使用 /baoyan upcoming 查看更多。"

            try:
                await self.context.send_message(
                    unified_msg_origin, MessageChain(chain=[Plain(message)])
                )
                logger.info(f"已发送即将到期项目通知给用户 {unified_msg_origin}")
            except Exception as e:
                logger.error(f"发送即将到期项目通知失败: {e}")

    def generate_program_id(self, program):
        """生成项目的唯一ID"""
        # 使用名称、机构和描述的组合作为唯一标识
        return f"{program.get('name', '')}:{program.get('institute', '')}:{program.get('description', '')}"

    def parse_deadline(self, deadline_str):
        """解析截止日期字符串为datetime对象"""
        try:
            tz_bj = timezone(timedelta(hours=8))

            if "Z" in deadline_str:
                # UTC时间
                return datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            elif "+" in deadline_str or "-" in deadline_str and "T" in deadline_str:
                # 已经包含时区信息的ISO格式
                return datetime.fromisoformat(deadline_str)
            else:
                # 没有时区信息，假设是北京时间
                deadline = datetime.fromisoformat(deadline_str)
                return deadline.replace(tzinfo=tz_bj)
        except:
            return None

    async def update_data_from_remote(self):
        """从远程更新数据"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.remote_url) as response:
                    if response.status == 200:
                        data = await response.json()

                        # 保存到本地缓存
                        data_file = os.path.join(self.data_dir, "sources.json")
                        with open(data_file, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=4)

                        # 更新内存中的数据
                        self.data_sources = data
                        if self.data_sources and not self.default_source:
                            self.default_source = next(iter(self.data_sources))

                        self.last_update_time = time.time()
                        logger.info("保研信息数据更新成功")
                        return True
                    else:
                        logger.error(f"获取远程数据失败，状态码: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"更新远程数据出错: {e}")
            return False

    def load_data_sources(self):
        """加载本地缓存的数据源"""
        data_file = os.path.join(self.data_dir, "sources.json")

        if os.path.exists(data_file):
            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    self.data_sources = json.load(f)
                if self.data_sources:
                    self.default_source = next(iter(self.data_sources))
                self.last_update_time = os.path.getmtime(data_file)
                logger.info(
                    f"从本地缓存加载保研信息数据成功，共 {len(self.data_sources)} 个数据源"
                )
            except Exception as e:
                logger.error(f"从本地缓存加载数据源出错: {e}")
                self.data_sources = {}
        else:
            # 首次加载，尝试从远程获取
            logger.info("本地缓存不存在，将尝试从远程获取数据")
            asyncio.create_task(self.update_data_from_remote())

    def get_programs(self, tag: str = None) -> List[Dict]:
        """获取符合条件的保研项目"""
        source = self.default_source
        if source not in self.data_sources:
            return []

        programs = self.data_sources[source]
        result = []

        # 处理逗号分隔的多个标签
        tags = []
        tag = str(tag) if tag else None
        if tag:
            tags = [t.strip() for t in tag.split(",") if t.strip()]

        for program in programs:
            # 按标签筛选
            if tags:
                # 只要匹配其中一个标签即可
                if not any(t in program.get("tags", []) for t in tags):
                    continue

            result.append(program)

        return result

    def format_time_remaining(self, deadline_str: str) -> str:
        """格式化剩余时间"""
        if not deadline_str:
            return "未知"

        try:
            # 确保使用北京时间
            tz_bj = timezone(timedelta(hours=8))
            now = datetime.now(tz_bj)

            # 解析日期字符串并添加时区信息（如果没有）
            deadline = None
            if "Z" in deadline_str:
                # UTC时间
                deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            elif "+" in deadline_str or "-" in deadline_str and "T" in deadline_str:
                # 已经包含时区信息的ISO格式
                deadline = datetime.fromisoformat(deadline_str)
            else:
                # 没有时区信息，假设是北京时间
                deadline = datetime.fromisoformat(deadline_str)
                deadline = deadline.replace(tzinfo=tz_bj)

            if deadline < now:
                return "已截止"

            diff = deadline - now
            days = diff.days
            hours = diff.seconds // 3600

            if days > 0:
                return f"剩余 {days} 天 {hours} 小时"
            else:
                return f"剩余 {hours} 小时"
        except Exception as e:
            logger.error(f"格式化时间出错: {e}")
            return "未知"

    def format_program_text(self, program: Dict) -> str:
        """将项目信息格式化为文本"""
        deadline_str = program.get("deadline", "")
        deadline_display = self.format_time_remaining(deadline_str)
        tags_display = "、".join(program.get("tags", []))

        text = f"【{program['name']} - {program['institute']}】\n"
        text += f"描述: {program['description']}\n"
        text += f"截止日期: {deadline_display}\n"
        text += f"官方网站: {program['website']}\n"
        if tags_display:
            text += f"标签: {tags_display}\n"
        return text

    @filter.command_group("baoyan", alias={"by"})
    def baoyan(self):
        """保研信息查询指令组"""
        pass

    @baoyan.command("sub")
    async def subscribe(self, event: AstrMessageEvent, tags: str = None):
        """订阅保研项目通知

        Args:
            tags: 标签，可选，多个标签用逗号分隔。不填则接收所有通知
        """
        unified_msg_origin = event.unified_msg_origin
        tag_set = set()

        if tags:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            # 验证标签是否存在
            all_tags = set()
            for source, programs in self.data_sources.items():
                for program in programs:
                    if "tags" in program:
                        all_tags.update(program["tags"])

            # 检查无效的标签
            invalid_tags = [tag for tag in tag_list if tag not in all_tags]
            if invalid_tags:
                yield event.plain_result(
                    f"以下标签无效或不存在: {', '.join(invalid_tags)}\n"
                    f"请使用 /baoyan tags 查看所有可用标签"
                )
                return

            tag_set = set(tag_list)

        # 设置或更新订阅
        self.subscriptions[unified_msg_origin] = tag_set
        self.save_subscriptions()

        if tags:
            yield event.plain_result(
                f"已成功订阅保研信息，过滤标签: {', '.join(tag_set)}"
            )
        else:
            yield event.plain_result("已成功订阅保研信息，将接收所有通知")

    @baoyan.command("unsub")
    async def unsubscribe(self, event: AstrMessageEvent):
        """取消订阅保研项目通知"""
        unified_msg_origin = event.unified_msg_origin

        if unified_msg_origin in self.subscriptions:
            del self.subscriptions[unified_msg_origin]
            self.save_subscriptions()
            yield event.plain_result("已成功取消订阅保研信息通知")
        else:
            yield event.plain_result("您当前没有订阅保研信息通知")

    @baoyan.command("status")
    async def subscription_status(self, event: AstrMessageEvent):
        """查看当前订阅状态"""
        unified_msg_origin = event.unified_msg_origin

        if unified_msg_origin in self.subscriptions:
            tags = self.subscriptions[unified_msg_origin]
            if tags:
                yield event.plain_result(
                    f"您当前已订阅保研信息，过滤标签: {', '.join(tags)}"
                )
            else:
                yield event.plain_result("您当前已订阅所有保研信息")
        else:
            yield event.plain_result("您当前没有订阅保研信息通知")

    @baoyan.command("list", alias={"ls"})
    async def list_programs(
        self,
        event: AstrMessageEvent,
        tag: str = None,
    ):
        """列出保研项目

        Args:
            tag: 筛选标签，可选，多个标签用逗号分隔
        """
        source = self.default_source
        if source not in self.data_sources:
            yield event.plain_result(
                f"当前数据源 '{source}' 不存在，请使用 /baoyan sources 查看可用的数据源"
            )
            return

        programs = self.get_programs(tag)

        if not programs:
            yield event.plain_result("没有找到符合条件的保研项目")
            return

        # 使用文本格式输出
        result = f"== 保研项目列表 ==\n数据源: {source}\n"
        if tag:
            result += f"标签筛选: {tag}\n"
        result += "\n"

        # 显示数量限制
        display_limit = self.max_display_items

        for i, program in enumerate(programs[:display_limit], 1):
            result += f"{i}. {self.format_program_text(program)}\n"

        yield event.plain_result(result)

        if len(programs) > display_limit:
            yield event.plain_result(
                f"共找到 {len(programs)} 个项目，仅显示前 {display_limit} 个。请使用更具体的标签筛选。"
            )

    @baoyan.command("sources")
    async def list_sources(self, event: AstrMessageEvent):
        """列出所有可用的数据源"""
        if not self.data_sources:
            yield event.plain_result("当前没有可用的数据源")
            return

        result = "可用的数据源:\n"
        for source, programs in self.data_sources.items():
            result += f"- {source}: 包含 {len(programs)} 个项目\n"

        result += f"\n当前默认数据源: {self.default_source}"
        yield event.plain_result(result)

    @baoyan.command("set_default")
    async def set_default_source(self, event: AstrMessageEvent, source: str):
        """设置默认数据源

        Args:
            source: 数据源名称
        """
        if source not in self.data_sources:
            yield event.plain_result(
                f"数据源 '{source}' 不存在，可用的数据源有: {', '.join(self.data_sources.keys())}"
            )
            return

        self.default_source = source
        yield event.plain_result(f"已将默认数据源设置为: {source}")

    @baoyan.command("tags")
    async def list_tags(self, event: AstrMessageEvent):
        """列出数据源中的所有标签"""
        source = self.default_source
        if source not in self.data_sources:
            yield event.plain_result(
                f"当前数据源 '{source}' 不存在，请使用 /baoyan sources 查看可用的数据源"
            )
            return

        all_tags = set()
        for program in self.data_sources[source]:
            if "tags" in program:
                all_tags.update(program["tags"])

        if not all_tags:
            yield event.plain_result(f"数据源 '{source}' 中没有定义标签")
            return

        yield event.plain_result(
            f"数据源 '{source}' 中的所有标签:\n{', '.join(sorted(all_tags))}"
        )

    @baoyan.command("upcoming", alias={"up"})
    async def list_upcoming(self, event: AstrMessageEvent, tag: str = None):
        """列出30天内即将截止的项目

        Args:
            tag: 筛选标签，可选，多个标签用逗号分隔
        """
        source = self.default_source
        days = 30  # 固定为30天

        if source not in self.data_sources:
            yield event.plain_result(
                f"当前数据源 '{source}' 不存在，请使用 /baoyan sources 查看可用的数据源"
            )
            return

        # 使用北京时间
        tz_bj = timezone(timedelta(hours=8))
        now = datetime.now(tz_bj)
        deadline_ts = now.timestamp() + days * 86400

        # 处理逗号分隔的多个标签
        tags = []
        tag = str(tag) if tag else None
        if tag:
            tags = [t.strip() for t in tag.split(",") if t.strip()]

        upcoming_programs = []
        for program in self.data_sources[source]:
            try:
                deadline_str = program.get("deadline", "")
                if not deadline_str:
                    continue

                # 解析日期字符串并添加时区信息（如果没有）
                deadline = None
                if "Z" in deadline_str:
                    # UTC时间
                    deadline = datetime.fromisoformat(
                        deadline_str.replace("Z", "+00:00")
                    )
                elif "+" in deadline_str or "-" in deadline_str and "T" in deadline_str:
                    # 已经包含时区信息的ISO格式
                    deadline = datetime.fromisoformat(deadline_str)
                else:
                    # 没有时区信息，假设是北京时间
                    deadline = datetime.fromisoformat(deadline_str)
                    deadline = deadline.replace(tzinfo=tz_bj)

                # 如果指定了标签，进行筛选
                if tags:
                    # 只要匹配其中一个标签即可
                    if not any(t in program.get("tags", []) for t in tags):
                        continue

                # 检查是否在时间范围内
                program_deadline_ts = deadline.timestamp()
                if now.timestamp() <= program_deadline_ts <= deadline_ts:
                    upcoming_programs.append(program)
            except Exception as e:
                logger.error(
                    f"处理截止日期时出错: {e}, deadline_str={program.get('deadline', '')}"
                )

        # 按截止日期升序排序
        upcoming_programs.sort(key=lambda x: self.get_program_timestamp(x["deadline"]))

        if not upcoming_programs:
            yield event.plain_result(
                f"未找到 {days} 天内即将截止的项目"
                + (f"（标签：{tag}）" if tag else "")
            )
            return

        # 使用文本格式输出
        result = f"== {days}天内即将截止的项目 =="
        result += f"\n数据源: {source}"
        if tag:
            result += f"\n标签筛选: {tag}"
        result += "\n\n"

        # 显示数量限制
        display_limit = self.max_display_items

        for i, program in enumerate(upcoming_programs[:display_limit], 1):
            result += f"{i}. {self.format_program_text(program)}\n"

        yield event.plain_result(result)

        if len(upcoming_programs) > display_limit:
            yield event.plain_result(
                f"共找到 {len(upcoming_programs)} 个即将截止的项目，仅显示前 {display_limit} 个。"
            )

    def get_program_timestamp(self, deadline_str: str) -> float:
        """获取项目截止日期的时间戳，用于排序"""
        if not deadline_str:
            return float("inf")  # 没有截止日期的放在最后

        try:
            # 确保使用北京时间
            tz_bj = timezone(timedelta(hours=8))

            # 解析日期字符串并添加时区信息（如果没有）
            if "Z" in deadline_str:
                # UTC时间
                deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            elif "+" in deadline_str or "-" in deadline_str and "T" in deadline_str:
                # 已经包含时区信息的ISO格式
                deadline = datetime.fromisoformat(deadline_str)
            else:
                # 没有时区信息，假设是北京时间
                deadline = datetime.fromisoformat(deadline_str)
                deadline = deadline.replace(tzinfo=tz_bj)

            return deadline.timestamp()
        except Exception as e:
            logger.error(f"获取时间戳出错: {e}")
            return float("inf")  # 出错的放在最后

    @baoyan.command("update")
    async def manual_update(self, event: AstrMessageEvent):
        """手动更新数据源"""
        yield event.plain_result("正在更新保研信息数据，请稍候...")
        success = await self.update_data_from_remote()

        if success:
            yield event.plain_result("保研信息数据更新成功！")
        else:
            yield event.plain_result("保研信息数据更新失败，请稍后再试或检查网络连接。")

    @baoyan.command("detail")
    async def program_detail(self, event: AstrMessageEvent, name: str):
        """查看项目详细信息

        Args:
            name: 项目名称或学校名称关键词
        """
        source = self.default_source
        if source not in self.data_sources:
            yield event.plain_result(
                f"当前数据源 '{source}' 不存在，请使用 /baoyan sources 查看可用的数据源"
            )
            return

        matching_programs = []
        for program in self.data_sources[source]:
            if (
                name.lower() in program.get("name", "").lower()
                or name.lower() in program.get("institute", "").lower()
            ):
                matching_programs.append(program)

        if not matching_programs:
            yield event.plain_result(f"没有找到包含关键词 '{name}' 的项目")
            return

        if len(matching_programs) > 1:
            result = (
                f"找到 {len(matching_programs)} 个匹配项目，请提供更具体的关键词:\n\n"
            )
            for i, program in enumerate(matching_programs[:5], 1):
                result += f"{i}. {program['name']} - {program['institute']}\n"

            if len(matching_programs) > 5:
                result += f"... 等 {len(matching_programs)} 个项目"

            yield event.plain_result(result)
            return

        # 只有一个匹配项目，显示详细信息
        program = matching_programs[0]
        deadline_display = self.format_time_remaining(program["deadline"])
        tags_display = "、".join(program.get("tags", []))

        result = "== 项目详情 ==\n"
        result += f"学校: {program['name']}\n"
        result += f"机构: {program['institute']}\n"
        result += f"描述: {program['description']}\n"
        result += f"截止日期: {program['deadline']} ({deadline_display})\n"
        result += f"官方网站: {program['website']}\n"
        if tags_display:
            result += f"标签: {tags_display}"

        yield event.plain_result(result)

    @baoyan.command("search")
    async def search_programs(self, event: AstrMessageEvent, keyword: str):
        """搜索项目（模糊搜索学校和机构名称）

        Args:
            keyword: 搜索关键词
        """
        source = self.default_source
        if source not in self.data_sources:
            yield event.plain_result(
                f"当前数据源 '{source}' 不存在，请使用 /baoyan sources 查看可用的数据源"
            )
            return

        if not keyword:
            yield event.plain_result("请提供搜索关键词")
            return

        # 转换为小写以进行不区分大小写的搜索
        keyword = keyword.lower()
        matching_programs = []

        # 在学校名称和机构名称中搜索关键词
        for program in self.data_sources[source]:
            if (
                keyword in program.get("name", "").lower()
                or keyword in program.get("institute", "").lower()
            ):
                matching_programs.append(program)

        if not matching_programs:
            yield event.plain_result(f"没有找到包含关键词 '{keyword}' 的项目")
            return

        # 使用文本格式输出
        result = f"== 搜索结果: '{keyword}' ==\n数据源: {source}\n找到 {len(matching_programs)} 个匹配项目\n\n"

        # 显示数量限制
        display_limit = self.max_display_items

        for i, program in enumerate(matching_programs[:display_limit], 1):
            result += f"{i}. {self.format_program_text(program)}\n"

        yield event.plain_result(result)

        if len(matching_programs) > display_limit:
            yield event.plain_result(
                f"共找到 {len(matching_programs)} 个匹配项目，仅显示前 {display_limit} 个。请尝试使用更具体的关键词。"
            )

    # @filter.command("test")
    # async def test(self, event: AstrMessageEvent):
    #     # 模拟插入数据
    #     test_data = {
    #         "name": "测试项目",
    #         "institute": "测试机构",
    #         "description": "这是一个测试项目",
    #         "deadline": "2023-12-31T23:59:59+08:00",
    #         "website": "https://example.com",
    #         "tags": ["测试", "示例"],
    #     }
    #     self.data_sources[self.default_source].append(test_data)
    #     yield event.plain_result("测试数据已插入")

    async def terminate(self):
        """插件停用时保存数据"""
        self.update_task.cancel()
        self.notification_task.cancel()
        self.save_subscriptions()
        self.save_known_programs()
