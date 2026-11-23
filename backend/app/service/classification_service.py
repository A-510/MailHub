from sqlalchemy.orm import Session

from app.model.entities import ClassificationRule
from app.repository.rule_repo import rule_repo


DEFAULT_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    ("github.com", "work"),
    ("gitlab", "work"),
    ("jira", "work"),
    ("company.com", "work"),
    ("slack", "work"),
    ("edu.cn", "study"),
    ("coursera", "study"),
    ("scholar", "study"),
    ("arxiv", "study"),
    ("bilibili", "social"),
    ("qq.com", "social"),
    ("steam", "social"),
    ("weibo", "social"),
    ("discord", "social"),
    ("newsletter", "subscription"),
    ("digest", "subscription"),
    ("noreply", "subscription"),
    ("unsubscribe", "subscription"),
]


class ClassificationService:
    """邮件智能分类服务，优先匹配用户自定义规则，其次使用默认关键词映射。"""

    def classify(
        self,
        db: Session,
        sender_email: str,
        sender_name: str,
        subject: str,
    ) -> str:
        """根据发件人与主题计算邮件分类（work / study / social / subscription）。"""
        rules: list[ClassificationRule] = rule_repo.list_all(db)
        field_values = {
            "sender_email": sender_email.lower(),
            "sender_name": sender_name.lower(),
            "subject": subject.lower(),
        }
        for rule in rules:
            if not rule.is_enabled:
                continue
            target_text = field_values.get(rule.field, "")
            if rule.pattern.lower() in target_text:
                return rule.target_category

        combined = f"{sender_email} {sender_name} {subject}".lower()
        for keyword, category in DEFAULT_CATEGORY_KEYWORDS:
            if keyword in combined:
                return category

        return "work"


classification_service = ClassificationService()
