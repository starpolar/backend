import pytest

from app.models.post.enums import PostType
from app.models.view.enums import ViewedStatus


@pytest.fixture
def user(user_manager):
    yield user_manager.create_cognito_only_user('pbuid', 'pbUname')


@pytest.fixture
def comment(user, post_manager, comment_manager):
    post = post_manager.add_post(user.id, 'pid', PostType.TEXT_ONLY, text='go go')
    yield comment_manager.add_comment('cid', post.id, user.id, 'run far')


@pytest.fixture
def user2(user_manager):
    yield user_manager.create_cognito_only_user('pbuid2', 'pbUname2')


@pytest.fixture
def user3(user_manager):
    yield user_manager.create_cognito_only_user('pbuid3', 'pbUname3')


def test_serialize(comment_manager, comment, user, view_manager):
    # serialize as the comment's author
    resp = comment.serialize(user.id)
    assert resp.pop('commentedBy')['userId'] == user.id
    assert resp.pop('viewedStatus') == ViewedStatus.VIEWED
    assert resp == comment.item

    # serialize as another user that has not viewed the comment
    other_user_id = 'ouid'
    resp = comment.serialize(other_user_id)
    assert resp.pop('commentedBy')['userId'] == user.id
    assert resp.pop('viewedStatus') == ViewedStatus.NOT_VIEWED
    assert resp == comment.item

    # the other user views the comment
    view_manager.record_views('comment', [comment.id], other_user_id)

    # serialize as another user that *has* viewed the comment
    other_user_id = 'ouid'
    resp = comment.serialize(other_user_id)
    assert resp.pop('commentedBy')['userId'] == user.id
    assert resp.pop('viewedStatus') == ViewedStatus.VIEWED
    assert resp == comment.item


def test_delete(comment, post_manager, comment_manager, user2, user3, view_manager):
    # verify it's visible in the DB
    comment_item = comment.dynamo.get_comment(comment.id)
    assert comment_item['commentId'] == comment.id

    # check the post's comment count
    post = post_manager.get_post(comment.item['postId'])
    assert post.item['commentCount'] == 1

    # add two views to the comment, verify we see them
    view_manager.record_views('comment', [comment.id], user2.id)
    view_manager.record_views('comment', [comment.id], user3.id)
    assert len(list(view_manager.dynamo.generate_views(comment.item['partitionKey']))) == 2

    # delete the comment
    comment.delete()

    # verify in-memory item still exists, but not in DB anymore
    assert comment.item['commentId'] == comment.id
    assert comment.dynamo.get_comment(comment.id) is None

    # check the post's comment count has decremented
    post = post_manager.get_post(comment.item['postId'])
    assert post.item['commentCount'] == 0

    # check the two comment views have also been deleted
    assert list(view_manager.dynamo.generate_views(comment.item['partitionKey'])) == []


def test_delete_cant_decrement_post_comment_count_below_zero(comment, post_manager):
    # sneak behind the model and lower the post's comment count
    transacts = [post_manager.dynamo.transact_decrement_comment_count(comment.item['postId'])]
    post_manager.dynamo.client.transact_write_items(transacts)

    # deleting the comment should fail
    with pytest.raises(comment.dynamo.client.exceptions.ConditionalCheckFailedException):
        comment.delete()

    # verify the comment is still in the DB
    comment_item = comment.dynamo.get_comment(comment.id)
    assert comment_item['commentId'] == comment.id
