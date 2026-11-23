from sqlalchemy import select
from sqlalchemy.orm import Session

from app.model.entities import ClassificationRule


class RuleRepository:
    """自动分类规则数据库仓储层。"""

    def list_all(self, db: Session) -> list[ClassificationRule]:
        """按创建时间排序返回全部分类规则。"""
        return list(db.scalars(select(ClassificationRule).order_by(ClassificationRule.id.asc())).all())

    def get_by_id(self, db: Session, rule_id: int) -> ClassificationRule | None:
        """按主键查询分类规则。"""
        return db.get(ClassificationRule, rule_id)

    def create(self, db: Session, rule: ClassificationRule) -> ClassificationRule:
        """创建新的分类规则。"""
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return rule

    def save(self, db: Session, rule: ClassificationRule) -> ClassificationRule:
        """保存规则修改。"""
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return rule

    def delete(self, db: Session, rule: ClassificationRule) -> None:
        """删除规则。"""
        db.delete(rule)
        db.commit()


rule_repo = RuleRepository()
