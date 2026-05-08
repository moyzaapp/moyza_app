from sqlalchemy.orm import Session

from app.models.role import Role
from app.models.permission import Permission
from app.models.user import User

from app.core.password import hash_password


def seed_initial_data(db: Session):

    # =========================
    # ROLES
    # =========================

    admin_role = db.query(Role).filter(Role.name == "admin").first()

    if not admin_role:
        admin_role = Role(name="admin")
        db.add(admin_role)

    manager_role = db.query(Role).filter(Role.name == "manager").first()

    if not manager_role:
        manager_role = Role(name="manager")
        db.add(manager_role)

    agent_role = db.query(Role).filter(Role.name == "agent").first()

    if not agent_role:
        agent_role = Role(name="agent")
        db.add(agent_role)

    db.commit()

    # =========================
    # PERMISSIONS
    # =========================

    permissions_list = [
        "user.create",
        "user.read",
        "user.update",
        "user.delete",
        "client.create",
        "client.read",
        "client.update",
        "client.delete",
    ]

    permissions = []

    for perm_code in permissions_list:

        permission = db.query(Permission).filter(
            Permission.code == perm_code
        ).first()

        if not permission:
            permission = Permission(code=perm_code)
            db.add(permission)

        permissions.append(permission)

    db.commit()

    # =========================
    # ASSIGN PERMISSIONS
    # =========================

    admin_role.permissions = permissions

    manager_role.permissions = [
        p for p in permissions
        if p.code in [
            "client.create",
            "client.read",
            "client.update",
            "user.read"
        ]
    ]

    agent_role.permissions = [
        p for p in permissions
        if p.code in [
            "client.read"
        ]
    ]

    db.commit()

    # =========================
    # ADMIN USER
    # =========================

    admin_user = db.query(User).filter(
        User.email == "admin@moyza.com"
    ).first()

    if not admin_user:

        admin_user = User(
            email="adminadmin@moyza.com",
            full_name="Admin Moyza",
            hashed_password=hash_password("Admin123*"),
            role_id=admin_role.id
        )

        db.add(admin_user)

    db.commit()

    print("Initial data seeded successfully.")