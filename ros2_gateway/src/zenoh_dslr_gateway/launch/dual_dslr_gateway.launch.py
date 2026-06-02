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
                name="zenoh_dslr_gateway_6d",
                output="screen",
                parameters=[
                    PathJoinSubstitution(
                        [FindPackageShare("zenoh_dslr_gateway"), "config", "canon_eos_6d.params.yaml"]
                    )
                ],
            ),
            Node(
                package="zenoh_dslr_gateway",
                executable="gateway_node",
                name="zenoh_dslr_gateway_m50",
                output="screen",
                parameters=[
                    PathJoinSubstitution(
                        [FindPackageShare("zenoh_dslr_gateway"), "config", "canon_eos_m50.params.yaml"]
                    )
                ],
            ),
        ]
    )
