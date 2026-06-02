from launch import LaunchDescription
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            Node(
                package="zenoh_dslr_gateway",
                executable="gateway_node",
                name="zenoh_dslr_gateway",
                output="screen",
                parameters=[
                    PathJoinSubstitution(
                        [FindPackageShare("zenoh_dslr_gateway"), "config", "gateway.params.yaml"]
                    )
                ],
            )
        ]
    )
