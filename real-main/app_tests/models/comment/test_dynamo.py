import pendulum
import pytest

from app.models.comment.dynamo import CommentDynamo
from app.models.comment.exceptions import CommentAlreadyExists, CommentDoesNotExist


@pytest.fixture
def comment_dynamo(dynamo_client):
    yield CommentDynamo(dynamo_client)


def test_add_comment(comment_dynamo):
    comment_id = 'cid'
    post_id = 'pid'
    user_id = 'uid'
    text = 'text @dog'
    text_tags = [{'tag': '@dog', 'userId': 'duid'}]
    now = pendulum.now('utc')

    # add the comment to the DB, verify format
    comment_item = comment_dynamo.add_comment(comment_id, post_id, user_id, text, text_tags, now)
    assert comment_dynamo.get_comment(comment_id) == comment_item
    assert comment_item == {
        'partitionKey': 'comment/cid',
        'sortKey': '-',
        'schemaVersion': 1,
        'gsiA1PartitionKey': 'comment/pid',
        'gsiA1SortKey': now.to_iso8601_string(),
        'gsiA2PartitionKey': 'comment/uid',
        'gsiA2SortKey': now.to_iso8601_string(),
        'commentId': 'cid',
        'postId': 'pid',
        'userId': 'uid',
        'text': text,
        'textTags': text_tags,
        'commentedAt': now.to_iso8601_string(),
    }


def test_cant_add_comment_same_comment_id(comment_dynamo):
    comment_id = 'cid'
    post_id = 'pid'
    user_id = 'uid'
    text = 'lore'
    text_tags = []

    # add a comment with that comment id
    comment_dynamo.add_comment(comment_id, post_id, user_id, text, text_tags)

    # verify we can't add another comment with the same id
    with pytest.raises(CommentAlreadyExists):
        comment_dynamo.add_comment(comment_id, post_id, user_id, text, text_tags)


def test_delete_comment(comment_dynamo):
    comment_id = 'cid'
    post_id = 'pid'
    user_id = 'uid'
    text = 'lore'
    text_tags = []

    # delete a comment that doesn't exist
    assert comment_dynamo.delete_comment(comment_id) is None

    # add the comment, verify
    comment_dynamo.add_comment(comment_id, post_id, user_id, text, text_tags)
    comment_item = comment_dynamo.get_comment(comment_id)
    assert comment_item['commentId'] == comment_id

    # delete the comment, verify
    assert comment_dynamo.delete_comment(comment_id)
    assert comment_dynamo.get_comment(comment_id) is None


def test_generate_by_post(comment_dynamo):
    post_id = 'pid'

    # add a comment on an unrelated post
    comment_dynamo.add_comment('coid', 'poid', 'uiod', 't', [])

    # post has no comments, generate them
    assert list(comment_dynamo.generate_by_post(post_id)) == []

    # add two comments to that post
    comment_id_1 = 'cid1'
    comment_id_2 = 'cid2'
    comment_dynamo.add_comment(comment_id_1, post_id, 'uid1', 't', [])
    comment_dynamo.add_comment(comment_id_2, post_id, 'uid1', 't', [])

    # generate comments, verify order
    comment_items = list(comment_dynamo.generate_by_post(post_id))
    assert len(comment_items) == 2
    assert comment_items[0]['commentId'] == comment_id_1
    assert comment_items[1]['commentId'] == comment_id_2


def test_generate_by_user(comment_dynamo):
    user_id = 'uid'

    # add a comment by an unrelated user
    comment_dynamo.add_comment('coid', 'poid', 'uiod', 't', [])

    # user has no comments, generate them
    assert list(comment_dynamo.generate_by_user(user_id)) == []

    # add two comments by that user
    comment_id_1 = 'cid1'
    comment_id_2 = 'cid2'
    comment_dynamo.add_comment(comment_id_1, 'pid1', user_id, 't', [])
    comment_dynamo.add_comment(comment_id_2, 'pid2', user_id, 't', [])

    # generate comments, verify order
    comment_items = list(comment_dynamo.generate_by_user(user_id))
    assert len(comment_items) == 2
    assert comment_items[0]['commentId'] == comment_id_1
    assert comment_items[1]['commentId'] == comment_id_2


def test_transact_increment_decrement_flag_count(comment_dynamo):
    comment_id = 'cid'

    # add a comment
    comment_dynamo.add_comment(comment_id, 'pid', 'uid', 'text', [])

    # check it has no flags
    comment_item = comment_dynamo.get_comment(comment_id)
    assert comment_item.get('flagCount', 0) == 0

    # check first increment works
    transacts = [comment_dynamo.transact_increment_flag_count(comment_id)]
    comment_dynamo.client.transact_write_items(transacts)
    comment_item = comment_dynamo.get_comment(comment_id)
    assert comment_item.get('flagCount', 0) == 1

    # check decrement works
    transacts = [comment_dynamo.transact_decrement_flag_count(comment_id)]
    comment_dynamo.client.transact_write_items(transacts)
    comment_item = comment_dynamo.get_comment(comment_id)
    assert comment_item.get('flagCount', 0) == 0

    # check can't decrement below zero
    transacts = [comment_dynamo.transact_decrement_flag_count(comment_id)]
    with pytest.raises(comment_dynamo.client.exceptions.TransactionCanceledException):
        comment_dynamo.client.transact_write_items(transacts)


def test_increment_viewed_by_count(comment_dynamo):
    # verify can't increment for comment that doesnt exist
    comment_id = 'comment-id'
    with pytest.raises(CommentDoesNotExist):
        comment_dynamo.increment_viewed_by_count(comment_id)

    # create the comment
    comment_dynamo.add_comment(comment_id, 'pd', 'uid', 'lore ipsum', [])

    # verify it has no view count
    comment_item = comment_dynamo.get_comment(comment_id)
    assert comment_item.get('viewedByCount', 0) == 0

    # record a view
    comment_item = comment_dynamo.increment_viewed_by_count(comment_id)
    assert comment_item['commentId'] == comment_id
    assert comment_item['viewedByCount'] == 1

    # verify it really got the view count
    comment_item = comment_dynamo.get_comment(comment_id)
    assert comment_item['commentId'] == comment_id
    assert comment_item['viewedByCount'] == 1

    # record another view
    comment_item = comment_dynamo.increment_viewed_by_count(comment_id)
    assert comment_item['commentId'] == comment_id
    assert comment_item['viewedByCount'] == 2

    # verify it really got the view count
    comment_item = comment_dynamo.get_comment(comment_id)
    assert comment_item['commentId'] == comment_id
    assert comment_item['viewedByCount'] == 2
